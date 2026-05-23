import asyncio
import os
import asyncpg
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../.env"))


async def init():
    url = os.getenv("DATABASE_URL", "")
    # asyncpg doesn't use the SQLAlchemy prefix
    url = url.replace("postgresql+asyncpg://", "postgresql://")

    conn = await asyncpg.connect(url)

    with open(os.path.join(os.path.dirname(__file__), "db/schema.sql")) as f:
        schema = f.read()

    await conn.execute(schema)
    await conn.close()
    print("✓ Schema created successfully on Neon")


asyncio.run(init())
