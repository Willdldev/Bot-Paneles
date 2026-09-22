import os
import asyncpg

from config import DATABASE_URL

_pool: asyncpg.Pool | None = None
_SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    return _pool


async def init_schema():
    """Crea las tablas si no existen. Seguro de correr en cada arranque."""
    pool = await get_pool()
    with open(_SCHEMA_PATH, "r", encoding="utf-8") as f:
        schema = f.read()
    async with pool.acquire() as conn:
        await conn.execute(schema)
