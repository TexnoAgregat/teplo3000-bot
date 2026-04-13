import asyncio, logging, os, json
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker, relationship, selectinload
from sqlalchemy import Column, Integer, String, Float, Text, ForeignKey, Boolean, DateTime, select
from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL")
PORT = int(os.environ.get("PORT", "8000"))
DATABASE_URL = os.getenv("DATABASE_URL")

if not TOKEN or not ADMIN_ID or not DATABASE_URL:
    raise Exception("BOT_TOKEN, ADMIN_ID, and DATABASE_URL must be set")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)

engine = create_async_engine(DATABASE_URL, echo=False)
Base = declarative_base()
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True)
    name = Column(String); price = Column(Float); description = Column(Text)
    brand = Column(String, default=""); power = Column(Integer, default=0)
    mount_type = Column(String, default=""); in_stock = Column(Boolean, default=True)
    quantity = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    images = relationship("ProductImage", back_populates="product", cascade="all, delete-orphan")

class ProductImage(Base):
    __tablename__ = "product_images"
    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id"))
    file_id = Column(String); is_main = Column(Boolean, default=False)
    product = relationship("Product", back_populates="images")

class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True)
    customer_name = Column(String); phone = Column(String); email = Column(String, nullable=True)
    address = Column(Text, nullable=True); comment = Column(Text, nullable=True)
    items = Column(Text); total = Column(Float); status = Column(String, default="new")
    created_at = Column(DateTime, default=datetime.utcnow)

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.get("/api/products")
async def get_products():
    async with async_session() as session:
        result = await session.execute(select(Product).options(selectinload(Product.images)))
        products = result.scalars().all()
        return [{"id": p.id, "name": p.name, "price": p.price, "description": p.description,
                 "brand": p.brand, "power": p.power, "mount_type": p.mount_type,
                 "in_stock": p.in_stock, "quantity": p.quantity,
                 "images": [{"url": f"https://api.telegram.org/file/bot{TOKEN}/{img.file_id}", "is_main": img.is_main} for img in p.images]} for p in products]

@app.post("/api/order")
async def create_order(order_data: dict):
    try:
        items = order_data.get("items", []); total = order_data.get("total", 0)
        customer = order_data.get("customer", {})
        text = f"🛒 *Новый заказ!*\n\n👤 {customer.get('name')}\n📞 {customer.get('phone')}\n"
        if customer.get("email"): text += f"📧 {customer.get('email')}\n"
        if customer.get("address"): text += f"🏠 {customer.get('address')}\n"
        if customer.get("comment"): text += f"💬 {customer.get('comment')}\n"
        text += f"\n💰 Сумма: {total} ₽\n\n*Товары:*\n"
        for item in items: text += f"- {item['name']} x{item['quantity']} = {item['price']*item['quantity']} ₽\n"
        await bot.send_message(ADMIN_ID, text, parse_mode="Markdown")
        async with async_session() as session:
            order = Order(customer_name=customer.get('name'), phone=customer.get('phone'),
                          email=customer.get('email'), address=customer.get('address'),
                          comment=customer.get('comment'), items=json.dumps(items), total=total)
            session.add(order); await session.commit()
        return {"status": "ok"}
    except Exception as e: return {"status": "error"}

bot = Bot(token=TOKEN); dp = Dispatcher(storage=MemoryStorage())
def is_admin(u): return u == ADMIN_ID
def main_keyboard():
    b = ReplyKeyboardBuilder()
    b.add(KeyboardButton(text="➕ Добавить товар"), KeyboardButton(text="📋 Список товаров"))
    b.add(KeyboardButton(text="✏️ Редактировать"), KeyboardButton(text="📦 Заказы"))
    return b.adjust(2).as_markup(resize_keyboard=True)

@dp.message(Command("start"))
async def start(m: types.Message):
    if not is_admin(m.from_user.id): return m.answer("⛔ Доступ запрещён.")
    await m.answer("Админ-панель:", reply_markup=main_keyboard())

class AddProduct(StatesGroup):
    name = State(); price = State(); description = State(); brand = State()
    power = State(); mount_type = State(); quantity = State(); photo = State()

@dp.message(F.text == "➕ Добавить товар")
async def add_start(m: types.Message, state: FSMContext):
    if not is_admin(m.from_user.id): return
    await state.set_state(AddProduct.name); await m.answer("Введите название:")

@dp.message(AddProduct.name)
async def add_name(m: types.Message, state: FSMContext):
    await state.update_data(name=m.text); await state.set_state(AddProduct.price); await m.answer("Цена (число):")

@dp.message(AddProduct.price)
async def add_price(m: types.Message, state: FSMContext):
    try: p = float(m.text)
    except: return m.answer("Введите число!")
    await state.update_data(price=p); await state.set_state(AddProduct.description); await m.answer("Описание:")

@dp.message(AddProduct.description)
async def add_desc(m: types.Message, state: FSMContext):
    await state.update_data(description=m.text); await state.set_state(AddProduct.brand); await m.answer("Бренд:")

@dp.message(AddProduct.brand)
async def add_brand(m: types.Message, state: FSMContext):
    await state.update_data(brand=m.text); await state.set_state(AddProduct.power); await m.answer("Мощность (кВт, целое):")

@dp.message(AddProduct.power)
async def add_power(m: types.Message, state: FSMContext):
    try: p = int(m.text)
    except: return m.answer("Введите целое число!")
    await state.update_data(power=p); await state.set_state(AddProduct.mount_type); await m.answer("Тип монтажа (настенный/напольный):")

@dp.message(AddProduct.mount_type)
async def add_mount(m: types.Message, state: FSMContext):
    await state.update_data(mount_type=m.text.lower()); await state.set_state(AddProduct.quantity); await m.answer("Количество на складе:")

@dp.message(AddProduct.quantity)
async def add_quantity(m: types.Message, state: FSMContext):
    try: q = int(m.text)
    except: return m.answer("Введите число!")
    await state.update_data(quantity=q, in_stock=q>0); await state.set_state(AddProduct.photo)
    await m.answer("Отправьте фото (можно несколько). Когда закончите — /done")

@dp.message(AddProduct.photo, F.photo)
async def add_photo(m: types.Message, state: FSMContext):
    data = await state.get_data(); photos = data.get("photos", [])
    photos.append(m.photo[-1].file_id); await state.update_data(photos=photos)
    await m.answer(f"📸 Фото {len(photos)} добавлено. Отправьте ещё или /done")

@dp.message(Command("done"), AddProduct.photo)
async def add_done(m: types.Message, state: FSMContext):
    data = await state.get_data()
    if not data.get("name"): return m.answer("Ошибка.")
    async with async_session() as s:
        p = Product(name=data["name"], price=data["price"], description=data["description"],
                    brand=data.get("brand",""), power=data.get("power",0), mount_type=data.get("mount_type",""),
                    quantity=data.get("quantity",0), in_stock=data.get("in_stock",False))
        s.add(p); await s.flush()
        for i, fid in enumerate(data.get("photos",[])):
            s.add(ProductImage(product_id=p.id, file_id=fid, is_main=(i==0)))
        await s.commit()
    await m.answer(f"✅ Товар '{data['name']}' добавлен!", reply_markup=main_keyboard()); await state.clear()

@dp.message(F.text == "📋 Список товаров")
async def list_products(m: types.Message):
    if not is_admin(m.from_user.id): return
    async with async_session() as s:
        prods = (await s.execute(select(Product).order_by(Product.id))).scalars().all()
        if not prods: return m.answer("В базе пусто.")
        txt = "📋 *Товары:*\n" + "\n".join(f"{p.id}. {p.name} — {p.price} ₽" for p in prods[:20])
        await m.answer(txt, parse_mode="Markdown")

class EditProduct(StatesGroup):
    waiting_for_id = State(); waiting_for_field = State(); waiting_for_value = State()

@dp.message(F.text == "✏️ Редактировать")
async def edit_start(m: types.Message, state: FSMContext):
    if not is_admin(m.from_user.id): return
    await state.set_state(EditProduct.waiting_for_id); await m.answer("Введите ID товара:")

@dp.message(EditProduct.waiting_for_id)
async def edit_id(m: types.Message, state: FSMContext):
    try: pid = int(m.text)
    except: return m.answer("Введите число!")
    async with async_session() as s:
        if not await s.get(Product, pid): return m.answer("Товар не найден.")
    await state.update_data(edit_id=pid); await state.set_state(EditProduct.waiting_for_field)
    await m.answer("Что меняем?\n1-Название 2-Цена 3-Описание 4-Бренд 5-Мощность 6-Тип 7-Количество")

@dp.message(EditProduct.waiting_for_field)
async def edit_field(m: types.Message, state: FSMContext):
    fm = {"1":"name","2":"price","3":"desc","4":"brand","5":"power","6":"mount","7":"qty"}
    f = fm.get(m.text.strip())
    if not f: return m.answer("Неверный номер.")
    await state.update_data(edit_field=f); await state.set_state(EditProduct.waiting_for_value)
    pr = {"name":"Название:","price":"Цена:","desc":"Описание:","brand":"Бренд:","power":"Мощность (кВт):","mount":"Тип:","qty":"Количество:"}
    await m.answer(pr[f])

@dp.message(EditProduct.waiting_for_value)
async def edit_value(m: types.Message, state: FSMContext):
    data = await state.get_data(); pid, f = data.get("edit_id"), data.get("edit_field")
    async with async_session() as s:
        p = await s.get(Product, pid)
        if not p: return m.answer("Товар не найден.")
        try:
            if f=="name": p.name=m.text
            elif f=="price": p.price=float(m.text)
            elif f=="desc": p.description=m.text
            elif f=="brand": p.brand=m.text
            elif f=="power": p.power=int(m.text)
            elif f=="mount": p.mount_type=m.text.lower()
            elif f=="qty": q=int(m.text); p.quantity=q; p.in_stock=q>0
        except ValueError: return m.answer("Неверный формат числа.")
        s.add(p); await s.commit()
    await m.answer(f"✅ Товар {pid} обновлён!", reply_markup=main_keyboard()); await state.clear()

@dp.message(F.text == "📦 Заказы")
async def orders_list(m: types.Message):
    if not is_admin(m.from_user.id): return
    async with async_session() as s:
        ords = (await s.execute(select(Order).order_by(Order.created_at.desc()).limit(10))).scalars().all()
        if not ords: return m.answer("Заказов нет.")
        txt = "📦 *Последние заказы:*\n" + "\n".join(f"#{o.id} {o.customer_name} — {o.total} ₽ ({o.status})" for o in ords)
        await m.answer(txt, parse_mode="Markdown")

WEBHOOK_PATH = "/telegram"
@app.post(WEBHOOK_PATH)
async def webhook(update: dict):
    await dp.feed_update(bot, types.Update(**update)); return Response(status_code=200)

async def on_startup():
    async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
    await bot.set_webhook(f"{RENDER_EXTERNAL_URL}{WEBHOOK_PATH}")

async def main():
    await on_startup()
    await uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=PORT, log_level="info")).serve()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO); asyncio.run(main())