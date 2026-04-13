# api.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, selectinload
from sqlalchemy import select
import uvicorn
import os
import json
from bot import Product, ProductImage, Order, bot, ADMIN_ID  # TOKEN уберём отсюда

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL:
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(DATABASE_URL, echo=False)
else:
    engine = create_async_engine("sqlite+aiosqlite:///shop.db", echo=False)

async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# Явно получаем токен из окружения (как в bot.py)
TOKEN = os.getenv("BOT_TOKEN", "8666498291:AAH1PBKqxPSyTRdCKAGEn3xuo72IV0Dm3wQ")

@app.get("/api/products")
async def get_products():
    async with async_session() as session:
        result = await session.execute(select(Product).options(selectinload(Product.images)))
        products = result.scalars().all()
        return [{
            "id": p.id, "name": p.name, "price": p.price, "description": p.description,
            "brand": p.brand, "power": p.power, "mount_type": p.mount_type,
            "in_stock": p.in_stock, "quantity": p.quantity,
            "images": [
                {
                    "url": f"https://api.telegram.org/file/bot{TOKEN}/{img.file_id}",
                    "is_main": img.is_main
                }
                for img in p.images
            ]
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
        return {"status": "error", "detail": str(e)}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)