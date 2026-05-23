import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

load_dotenv()

_raw_url = os.getenv("DATABASE_URL", "")
DATABASE_URL = (
    _raw_url
    .replace("postgresql://", "postgresql+asyncpg://")
    .replace("?sslmode=require", "")
    .replace("&sslmode=require", "")
)

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"ssl": True},
)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
