# api.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
import uvicorn
import os
from bot import Product  # импортируем модель из bot.py

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Подключаем ту же БД
engine = create_async_engine("sqlite+aiosqlite:///shop.db")
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

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

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)