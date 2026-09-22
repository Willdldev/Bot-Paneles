import logging

from db import get_pool
from config import USUARIOS_PERMITIDOS_FIJOS, ADMINISTRADORES

logger = logging.getLogger(__name__)


async def obtener_roles(telegram_id: int) -> list[str] | None:
    """
    Devuelve la lista de roles de la persona si está autorizada, o None
    si no lo está. Revisa primero la lista fija del código (siempre
    disponible, no depende de la base de datos), luego la tabla `usuarios`.
    Si la consulta a la base falla, se niega el acceso (fail-safe): nunca
    se asume autorizado por defecto.
    """
    if telegram_id in USUARIOS_PERMITIDOS_FIJOS:
        return list(USUARIOS_PERMITIDOS_FIJOS[telegram_id][1])

    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            fila = await conn.fetchrow(
                "SELECT roles FROM usuarios WHERE telegram_id = $1", telegram_id
            )
        return list(fila["roles"]) if fila else None
    except Exception:
        logger.exception("Fallo consultando autorización en la base de datos; se niega el acceso.")
        return None


async def tiene_alguno_de(telegram_id: int, *roles_permitidos: str) -> bool:
    """True si la persona está autorizada y tiene al menos uno de los roles dados."""
    roles = await obtener_roles(telegram_id)
    if roles is None:
        return False
    return any(rol in roles for rol in roles_permitidos)


async def esta_autorizado(telegram_id: int) -> bool:
    return await obtener_roles(telegram_id) is not None


def es_administrador(telegram_id: int) -> bool:
    return telegram_id in ADMINISTRADORES
