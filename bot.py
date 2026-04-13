# bot.py
import asyncio
import logging
import os
import json
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker, relationship, selectinload
from sqlalchemy import Column, Integer, String, Float, Text, ForeignKey, Boolean, DateTime, select, update, delete
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# --- НАСТРОЙКИ ---
TOKEN = os.getenv("BOT_TOKEN", "8666498291:AAH1PBKqxPSyTRdCKAGEn3xuo72IV0Dm3wQ")
ADMIN_ID = int(os.getenv("ADMIN_ID", "246946262"))
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL")
PORT = int(os.environ.get("PORT", 8000))

# --- БАЗА ДАННЫХ (PostgreSQL) ---
DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL:
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(DATABASE_URL, echo=False)
else:
    engine = create_async_engine("sqlite+aiosqlite:///shop.db", echo=False)

Base = declarative_base()
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# --- МОДЕЛИ ---
class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True)
    name = Column(String)
    price = Column(Float)
    description = Column(Text)
    brand = Column(String, default="")
    power = Column(Integer, default=0)
    mount_type = Column(String, default="")  # настенный, напольный
    in_stock = Column(Boolean, default=True)
    quantity = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    images = relationship("ProductImage", back_populates="product", cascade="all, delete-orphan")

class ProductImage(Base):
    __tablename__ = "product_images"
    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id"))
    file_id = Column(String)  # Telegram file_id
    is_main = Column(Boolean, default=False)
    product = relationship("Product", back_populates="images")

class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True)
    customer_name = Column(String)
    phone = Column(String)
    email = Column(String, nullable=True)
    address = Column(Text, nullable=True)
    comment = Column(Text, nullable=True)
    items = Column(Text)  # JSON
    total = Column(Float)
    status = Column(String, default="new")
    created_at = Column(DateTime, default=datetime.utcnow)

# --- FASTAPI ---
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.get("/api/products")
async def get_products():
    async with async_session() as session:
        result = await session.execute(select(Product).options(selectinload(Product.images)))
        products = result.scalars().all()
        return [{
            "id": p.id, "name": p.name, "price": p.price, "description": p.description,
            "brand": p.brand, "power": p.power, "mount_type": p.mount_type,
            "in_stock": p.in_stock, "quantity": p.quantity,
            "images": [{"url": f"https://api.telegram.org/file/bot{TOKEN}/{img.file_id}", "is_main": img.is_main}
                       for img in p.images]
        } for p in products]

@app.post("/api/order")
async def create_order(order_data: dict):
    try:
        items = order_data.get("items", [])
        total = order_data.get("total", 0)
        customer = order_data.get("customer", {})
        text = f"🛒 *Новый заказ!*\n\n👤 {customer.get('name')}\n📞 {customer.get('phone')}\n"
        if customer.get("email"): text += f"📧 {customer.get('email')}\n"
        if customer.get("address"): text += f"🏠 {customer.get('address')}\n"
        if customer.get("comment"): text += f"💬 {customer.get('comment')}\n"
        text += f"\n💰 Сумма: {total} ₽\n\n*Товары:*\n"
        for item in items:
            text += f"- {item['name']} x{item['quantity']} = {item['price']*item['quantity']} ₽\n"
        await bot.send_message(ADMIN_ID, text, parse_mode="Markdown")
        async with async_session() as session:
            order = Order(customer_name=customer.get('name'), phone=customer.get('phone'),
                          email=customer.get('email'), address=customer.get('address'),
                          comment=customer.get('comment'), items=json.dumps(items), total=total)
            session.add(order)
            await session.commit()
        return {"status": "ok"}
    except Exception as e:
        logging.error(f"Order error: {e}")
        return {"status": "error"}

# --- ТЕЛЕГРАМ БОТ ---
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID

def main_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text="➕ Добавить товар"), KeyboardButton(text="📋 Список товаров"))
    builder.add(KeyboardButton(text="✏️ Редактировать"), KeyboardButton(text="📦 Заказы"))
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Доступ запрещён.")
        return
    await message.answer("Админ-панель:", reply_markup=main_keyboard())

# --- FSM для добавления ---
class AddProduct(StatesGroup):
    name = State()
    price = State()
    description = State()
    brand = State()
    power = State()
    mount_type = State()
    quantity = State()
    photo = State()

@dp.message(F.text == "➕ Добавить товар")
async def add_start(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    await state.set_state(AddProduct.name)
    await message.answer("Введите название:", reply_markup=types.ReplyKeyboardRemove())

@dp.message(AddProduct.name)
async def add_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await state.set_state(AddProduct.price)
    await message.answer("Цена (число):")

@dp.message(AddProduct.price)
async def add_price(message: types.Message, state: FSMContext):
    try:
        price = float(message.text)
    except ValueError:
        await message.answer("Введите число!")
        return
    await state.update_data(price=price)
    await state.set_state(AddProduct.description)
    await message.answer("Описание:")

@dp.message(AddProduct.description)
async def add_desc(message: types.Message, state: FSMContext):
    await state.update_data(description=message.text)
    await state.set_state(AddProduct.brand)
    await message.answer("Бренд (например, Baxi):")

@dp.message(AddProduct.brand)
async def add_brand(message: types.Message, state: FSMContext):
    await state.update_data(brand=message.text)
    await state.set_state(AddProduct.power)
    await message.answer("Мощность (кВт, целое число):")

@dp.message(AddProduct.power)
async def add_power(message: types.Message, state: FSMContext):
    try:
        power = int(message.text)
    except ValueError:
        await message.answer("Введите целое число!")
        return
    await state.update_data(power=power)
    await state.set_state(AddProduct.mount_type)
    await message.answer("Тип монтажа (настенный/напольный):")

@dp.message(AddProduct.mount_type)
async def add_mount(message: types.Message, state: FSMContext):
    await state.update_data(mount_type=message.text.lower())
    await state.set_state(AddProduct.quantity)
    await message.answer("Количество на складе:")

@dp.message(AddProduct.quantity)
async def add_quantity(message: types.Message, state: FSMContext):
    try:
        qty = int(message.text)
    except ValueError:
        await message.answer("Введите число!")
        return
    await state.update_data(quantity=qty, in_stock=(qty > 0))
    await state.set_state(AddProduct.photo)
    await message.answer("Отправьте фото (можно несколько). Когда закончите — отправьте команду /done")

@dp.message(AddProduct.photo, F.photo)
async def add_photo(message: types.Message, state: FSMContext):
    data = await state.get_data()
    photos = data.get("photos", [])
    photos.append(message.photo[-1].file_id)
    await state.update_data(photos=photos)
    await message.answer(f"📸 Фото {len(photos)} добавлено. Отправьте ещё или /done")

@dp.message(Command("done"), AddProduct.photo)
async def add_done(message: types.Message, state: FSMContext):
    data = await state.get_data()
    if not data.get("name"):
        await message.answer("Ошибка: нет данных. Начните заново.")
        await state.clear()
        return
    async with async_session() as session:
        product = Product(
            name=data["name"],
            price=data["price"],
            description=data["description"],
            brand=data.get("brand", ""),
            power=data.get("power", 0),
            mount_type=data.get("mount_type", ""),
            quantity=data.get("quantity", 0),
            in_stock=data.get("in_stock", False)
        )
        session.add(product)
        await session.flush()
        photos = data.get("photos", [])
        for i, file_id in enumerate(photos):
            img = ProductImage(product_id=product.id, file_id=file_id, is_main=(i == 0))
            session.add(img)
        await session.commit()
    await message.answer(f"✅ Товар '{data['name']}' добавлен!", reply_markup=main_keyboard())
    await state.clear()

# --- Список товаров ---
@dp.message(F.text == "📋 Список товаров")
async def list_products(message: types.Message):
    if not is_admin(message.from_user.id): return
    async with async_session() as session:
        result = await session.execute(select(Product).order_by(Product.id))
        products = result.scalars().all()
        if not products:
            await message.answer("В базе пусто.")
            return
        text = "📋 *Товары:*\n"
        for p in products[:20]:
            text += f"{p.id}. {p.name} — {p.price} ₽\n"
        await message.answer(text, parse_mode="Markdown")

# --- Редактирование (базовое) ---
@dp.message(F.text == "✏️ Редактировать")
async def edit_list(message: types.Message):
    if not is_admin(message.from_user.id): return
    async with async_session() as session:
        result = await session.execute(select(Product).order_by(Product.id))
        products = result.scalars().all()
        if not products:
            await message.answer("Нет товаров.")
            return
        builder = InlineKeyboardBuilder()
        for p in products[:10]:
            builder.add(InlineKeyboardButton(text=f"{p.id}. {p.name}", callback_data=f"edit_{p.id}"))
        await message.answer("Выберите товар:", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("edit_"))
async def edit_choose_field(callback: types.CallbackQuery, state: FSMContext):
    product_id = int(callback.data.split("_")[1])
    await state.update_data(edit_id=product_id)
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="Название", callback_data="field_name"))
    builder.add(InlineKeyboardButton(text="Цена", callback_data="field_price"))
    builder.add(InlineKeyboardButton(text="Описание", callback_data="field_desc"))
    builder.add(InlineKeyboardButton(text="Бренд", callback_data="field_brand"))
    builder.add(InlineKeyboardButton(text="Мощность", callback_data="field_power"))
    builder.add(InlineKeyboardButton(text="Тип", callback_data="field_mount"))
    builder.add(InlineKeyboardButton(text="Количество", callback_data="field_qty"))
    builder.adjust(2)
    await callback.message.edit_text("Что редактируем?", reply_markup=builder.as_markup())
    await callback.answer()

# (Обработчики редактирования можно добавить позже — пока базовая структура)

# --- Заказы (просмотр) ---
@dp.message(F.text == "📦 Заказы")
async def orders_list(message: types.Message):
    if not is_admin(message.from_user.id): return
    async with async_session() as session:
        result = await session.execute(select(Order).order_by(Order.created_at.desc()).limit(10))
        orders = result.scalars().all()
        if not orders:
            await message.answer("Заказов пока нет.")
            return
        text = "📦 *Последние заказы:*\n"
        for o in orders:
            text += f"#{o.id} {o.customer_name} — {o.total} ₽ ({o.status})\n"
        await message.answer(text, parse_mode="Markdown")

# --- ВЕБХУКИ ---
WEBHOOK_PATH = "/telegram"
@app.post(WEBHOOK_PATH)
async def bot_webhook(update: dict):
    telegram_update = types.Update(**update)
    await dp.feed_update(bot, telegram_update)
    return Response(status_code=200)

@app.get("/healthcheck")
async def healthcheck():
    return {"status": "ok"}

async def on_startup():
    webhook_url = f"{RENDER_EXTERNAL_URL}{WEBHOOK_PATH}"
    await bot.set_webhook(webhook_url)
    logging.info(f"Webhook set to {webhook_url}")

async def on_shutdown():
    await bot.delete_webhook()
    await bot.session.close()

async def main():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    config = uvicorn.Config(app, host="0.0.0.0", port=PORT, log_level="info")
    server = uvicorn.Server(config)
    await on_startup()
    try:
        await server.serve()
    finally:
        await on_shutdown()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())