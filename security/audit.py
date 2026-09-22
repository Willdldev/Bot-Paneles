from db import get_pool


async def registrar_intento(
    telegram_id: int,
    nombre: str,
    comando: str,
    chat_id: int | None,
    chat_nombre: str | None,
    resultado: str,
    detalle: str | None = None,
):
    """Registra cada intento (autorizado o bloqueado) para poder auditar después con /auditoria."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO auditoria (telegram_id, nombre, comando, chat_id, chat_nombre, resultado, detalle)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            telegram_id, nombre, comando, chat_id, chat_nombre, resultado, detalle,
        )
