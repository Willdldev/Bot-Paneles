"""
Configuración central del bot.

Sigue el mismo modelo de seguridad usado en el bot de contabilidad de BNI:
- Lista fija de usuarios en el código (red de seguridad permanente).
- Administradores solo editables aquí, nunca desde Telegram ni variables de entorno.
- IDs de grupo vía variables de entorno, con blindaje contra valores mal escritos.
"""
import os
import logging

logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ["BOT_TOKEN"]
DATABASE_URL = os.environ["DATABASE_URL"]

# --- Capa 1: usuarios fijos en el código ------------------------------
# Red de seguridad que nunca depende de que la base de datos funcione.
# Formato: telegram_id: (nombre, [roles])  — una persona puede tener más de un rol.
# EDITA ESTO con tu propio ID de Telegram antes de desplegar (usa /chatid
# por privado, una vez el bot esté corriendo, para obtener tu ID).
USUARIOS_PERMITIDOS_FIJOS: dict[int, tuple[str, list[str]]] = {
    # 123456789: ("Willber De Luna", ["admin"]),
}

# --- Administradores ----------------------------------------------------
# Lista separada y más pequeña. NO se puede ampliar desde Telegram ni con
# variables de entorno — solo editando este archivo directamente.
ADMINISTRADORES: set[int] = {
    # 123456789,
}


def _parse_group_id(var_name: str) -> int | None:
    """Lee un ID de grupo desde una variable de entorno. Si el valor está
    vacío o no es un entero válido, lo ignora y loguea el problema en vez
    de tumbar el bot completo."""
    raw = os.environ.get(var_name, "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        logger.warning("%s tiene un valor inválido ('%s'); se ignora.", var_name, raw)
        return None


# --- Capas 2 y 3: los 4 grupos de operación -----------------------------
COMERCIAL_GROUP_ID = _parse_group_id("COMERCIAL_GROUP_ID")    # Reservar Paneles
ALMACEN_GROUP_ID = _parse_group_id("ALMACEN_GROUP_ID")        # Entrada paneles almacén
VALIDACION_GROUP_ID = _parse_group_id("VALIDACION_GROUP_ID")  # Inventario paneles
SALIDA_GROUP_ID = _parse_group_id("SALIDA_GROUP_ID")          # Salidas paneles de almacén
PRUEBAS_GROUP_ID = _parse_group_id("PRUEBAS_GROUP_ID")        # opcional, exento de capa 3

GRUPOS_CONFIGURADOS: set[int] = {
    gid for gid in (COMERCIAL_GROUP_ID, ALMACEN_GROUP_ID, VALIDACION_GROUP_ID, SALIDA_GROUP_ID)
    if gid is not None
}

# Mapea cada comando a la lista de grupos donde puede usarse. La mayoría
# de comandos vive en un solo grupo; los de solo consulta (como
# "inventario") pueden vivir en varios.
COMANDOS_POR_GRUPO: dict[str, set[int]] = {}


def _habilitar(comando: str, grupo_id: int | None):
    if grupo_id is not None:
        COMANDOS_POR_GRUPO.setdefault(comando, set()).add(grupo_id)


_habilitar("reservar", COMERCIAL_GROUP_ID)
_habilitar("pendientes", COMERCIAL_GROUP_ID)
_habilitar("reservas", COMERCIAL_GROUP_ID)
_habilitar("disponible", COMERCIAL_GROUP_ID)  # vista comercial: incluye pendiente por llegar
_habilitar("reportar_dano", COMERCIAL_GROUP_ID)
_habilitar("reportes_dano", COMERCIAL_GROUP_ID)

_habilitar("entrada", ALMACEN_GROUP_ID)
_habilitar("orden_pendiente", ALMACEN_GROUP_ID)
_habilitar("ordenes_pendientes", ALMACEN_GROUP_ID)
_habilitar("inventario", ALMACEN_GROUP_ID)  # conveniencia: almacén también consulta aquí
_habilitar("reportar_dano", ALMACEN_GROUP_ID)
_habilitar("reportes_dano", ALMACEN_GROUP_ID)

_habilitar("inventario", VALIDACION_GROUP_ID)
_habilitar("movimientos", VALIDACION_GROUP_ID)
_habilitar("movimientos", ALMACEN_GROUP_ID)  # conveniencia: almacén también consulta aquí

_habilitar("salida", SALIDA_GROUP_ID)

# --- Descripciones para el menú de comandos de Telegram (el que sale
# al escribir "/" en un chat) --------------------------------------
DESCRIPCIONES_COMANDOS: dict[str, str] = {
    "reservar": "Reservar paneles para un proyecto",
    "pendientes": "Reservas sin confirmar en Odoo",
    "reservas": "Ver todas las reservas activas",
    "disponible": "Ver disponible para vender",
    "reportar_dano": "Reportar paneles dañados",
    "reportes_dano": "Historial de paneles dañados",
    "entrada": "Registrar entrada de paneles",
    "orden_pendiente": "Registrar orden aún no llegada",
    "ordenes_pendientes": "Ver órdenes pendientes por llegar",
    "inventario": "Ver inventario físico en almacén",
    "movimientos": "Ver entradas y salidas de almacén",
    "salida": "Registrar salida de paneles",
    "cancelar": "Cancelar la operación en curso",
    "chatid": "Ver tu ID o el del grupo",
    "autorizar": "Dar de alta a una persona",
    "desautorizar": "Quitar acceso a una persona",
    "agregar_rol": "Sumar un rol a alguien",
    "quitar_rol": "Quitar un rol a alguien",
    "usuarios": "Ver usuarios autorizados",
    "auditoria": "Ver registro de auditoría",
    "ajustar": "Corregir un número de inventario",
    "cargar_inicial": "Cargar el inventario inicial",
}
