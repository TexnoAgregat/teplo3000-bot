# bot.py
import asyncio
import logging
import os
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy import Column, Integer, String, Float, select
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# --- НАСТРОЙКИ ---
TOKEN = os.getenv("BOT_TOKEN", "8666498291:AAH1PBKqxPSyTRdCKAGEn3xuo72IV0Dm3wQ")
ADMIN_ID = int(os.getenv("ADMIN_ID", "246946262"))
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL")  # Render подставит этот URL сам
PORT = int(os.environ.get("PORT", 8000))

# --- БАЗА ДАННЫХ ---
engine = create_async_engine("sqlite+aiosqlite:///shop.db", echo=False)
Base = declarative_base()
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True)
    name = Column(String)
    price = Column(Float)
    description = Column(String)

# --- FASTAPI ---
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/products")
async def get_products():
    async with async_session() as session:
        result = await session.execute(select(Product))
        products = result.scalars().all()
        return [
            {
                "id": p.id,
                "name": p.name,
                "price": p.price,
                "description": p.description,
                "brand": "Unknown",
                "power": 0,
                "image": "https://cdn-icons-png.flaticon.com/512/3198/3198405.png"
            }
            for p in products
        ]

# --- ТЕЛЕГРАМ БОТ ---
class AddProduct(StatesGroup):
    waiting_for_name = State()
    waiting_for_price = State()
    waiting_for_description = State()

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Доступ запрещён.")
        return
    await message.answer("Привет! /add — добавить товар\n/list — список\n/delete ID — удалить")

@dp.message(Command("add"))
async def cmd_add(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await message.answer("Введите название товара:")
    await state.set_state(AddProduct.waiting_for_name)

@dp.message(AddProduct.waiting_for_name)
async def process_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("Введите цену (только число):")
    await state.set_state(AddProduct.waiting_for_price)

@dp.message(AddProduct.waiting_for_price)
async def process_price(message: types.Message, state: FSMContext):
    try:
        price = float(message.text)
    except ValueError:
        await message.answer("Введите число.")
        return
    await state.update_data(price=price)
    await message.answer("Введите описание:")
    await state.set_state(AddProduct.waiting_for_description)

@dp.message(AddProduct.waiting_for_description)
async def process_description(message: types.Message, state: FSMContext):
    data = await state.get_data()
    async with async_session() as session:
        product = Product(name=data["name"], price=data["price"], description=message.text)
        session.add(product)
        await session.commit()
    await message.answer(f"✅ Товар '{data['name']}' добавлен!")
    await state.clear()

@dp.message(Command("list"))
async def cmd_list(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    async with async_session() as session:
        result = await session.execute(select(Product))
        products = result.scalars().all()
        if not products:
            await message.answer("В базе пусто.")
            return
        text = "📋 **Товары:**\n"
        for p in products:
            text += f"{p.id}. {p.name} — {p.price} ₽\n"
        await message.answer(text)

@dp.message(Command("delete"))
async def cmd_delete(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    try:
        prod_id = int(message.text.split()[1])
    except (IndexError, ValueError):
        await message.answer("Формат: /delete ID")
        return
    async with async_session() as session:
        product = await session.get(Product, prod_id)
        if not product:
            await message.answer("Товар не найден.")
            return
        await session.delete(product)
        await session.commit()
    await message.answer(f"🗑️ Товар {prod_id} удалён.")

# --- ЭНДПОИНТ ДЛЯ ВЕБХУКА И HEALTHCHECK ---
WEBHOOK_PATH = "/telegram"

@app.post(WEBHOOK_PATH)
async def bot_webhook(update: dict):
    """Обрабатывает входящие обновления от Telegram."""
    telegram_update = types.Update(**update)
    await dp.feed_update(bot, telegram_update)
    return Response(status_code=200)

@app.get("/healthcheck")
async def healthcheck():
    """Нужен для проверки работоспособности сервиса самим Render."""
    return {"status": "ok"}

# --- НАСТРОЙКА ВЕБХУКА ПРИ СТАРТЕ ---
async def on_startup():
    """Устанавливает вебхук при запуске приложения."""
    webhook_url = f"{RENDER_EXTERNAL_URL}{WEBHOOK_PATH}"
    await bot.set_webhook(webhook_url)
    logging.info(f"Webhook set to {webhook_url}")

async def on_shutdown():
    """Удаляет вебхук и закрывает сессию бота."""
    await bot.delete_webhook()
    await bot.session.close()

async def main():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Запускаем FastAPI с uvicorn
    config = uvicorn.Config(app, host="0.0.0.0", port=PORT, log_level="info")
    server = uvicorn.Server(config)

    # Выполняем действия при старте
    await on_startup()

    # Запускаем сервер
    try:
        await server.serve()
    finally:
        await on_shutdown()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())