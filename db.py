import os
from urllib.parse import urlsplit, unquote, parse_qs

import asyncpg

from config import DATABASE_URL, USUARIOS_PERMITIDOS_FIJOS

_pool: asyncpg.Pool | None = None
_SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")


def _parametros_de_conexion(url: str) -> dict:
    """
    Separa la URL de conexión nosotros mismos (host, puerto, usuario,
    contraseña, base, ssl) en vez de pasarle el DSN completo a asyncpg.

    Esto evita un bug conocido entre asyncpg y el validador de URLs más
    estricto que trajo Python 3.13 (relacionado a un parche de
    seguridad de CPython, CVE-2024-11168): si el DSN completo llega a
    tener corchetes en cualquier parte — por ejemplo, si a alguien se
    le olvidó reemplazar el "[YOUR-PASSWORD]" de la plantilla de
    Supabase por la contraseña real — la función interna de asyncpg
    que llama a urllib.parse.urlparse(dsn) revienta con un ValueError
    confuso ("... does not appear to be an IPv4 or IPv6 address").
    Parseando aquí y pasando los datos ya separados, asyncpg nunca
    vuelve a tocar ese camino de código.
    """
    partes = urlsplit(url)
    query = parse_qs(partes.query)
    sslmode = (query.get("sslmode") or [None])[0]

    return dict(
        host=partes.hostname,
        port=partes.port or 5432,
        user=unquote(partes.username) if partes.username else None,
        password=unquote(partes.password) if partes.password else None,
        database=partes.path.lstrip("/") or None,
        ssl=True if sslmode not in (None, "disable", "allow") else None,
    )


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            min_size=1, max_size=5, **_parametros_de_conexion(DATABASE_URL)
        )
    return _pool


async def init_schema():
    """Crea las tablas si no existen. Seguro de correr en cada arranque."""
    pool = await get_pool()
    with open(_SCHEMA_PATH, "r", encoding="utf-8") as f:
        schema = f.read()
    async with pool.acquire() as conn:
        await conn.execute(schema)


async def sembrar_usuarios_fijos():
    """
    Asegura que cada persona de la lista fija (config.USUARIOS_PERMITIDOS_FIJOS)
    tenga también una fila en la tabla `usuarios`.

    La lista fija le da acceso al bot sin depender de la base de datos (por
    diseño, como red de seguridad), pero varias tablas (despachos,
    ordenes_compra, reportes_dano...) guardan quién hizo cada acción con una
    llave foránea hacia usuarios(telegram_id). Sin esta fila, cualquier
    acción de una persona de la lista fija falla con una violación de
    llave foránea al intentar guardarse — es justo lo que le pasó al admin
    al confirmar una salida. Se corre en cada arranque; es seguro repetirlo.
    """
    if not USUARIOS_PERMITIDOS_FIJOS:
        return
    pool = await get_pool()
    async with pool.acquire() as conn:
        for telegram_id, (nombre, roles) in USUARIOS_PERMITIDOS_FIJOS.items():
            await conn.execute(
                """
                INSERT INTO usuarios (telegram_id, nombre, roles)
                VALUES ($1, $2, $3)
                ON CONFLICT (telegram_id) DO UPDATE
                    SET nombre = EXCLUDED.nombre, roles = EXCLUDED.roles
                """,
                telegram_id, nombre, list(roles),
            )
