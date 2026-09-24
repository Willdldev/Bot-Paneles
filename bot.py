import logging

from telegram import BotCommand, BotCommandScopeChat, BotCommandScopeAllPrivateChats
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters

from config import (
    BOT_TOKEN, DESCRIPCIONES_COMANDOS,
    COMERCIAL_GROUP_ID, ALMACEN_GROUP_ID, VALIDACION_GROUP_ID, SALIDA_GROUP_ID, PRUEBAS_GROUP_ID,
)
from db import init_schema, sembrar_usuarios_fijos
from handlers.ocr import precargar_lector
from security.guardian import guardian_global
from handlers import admin, inventario, comercial, almacen, salida, danos

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def _configurar_menus_comandos(application: Application):
    """
    Configura el menú de comandos que Telegram muestra al escribir "/"
    — uno distinto por grupo, según lo que de verdad se puede usar ahí,
    más uno general para chat privado (comandos de administración).
    """
    comandos_comercial = [
        "reservar", "pendientes", "reservas", "reserva", "disponible",
        "reportar_dano", "reportes_dano", "cancelar", "chatid",
    ]
    comandos_almacen = [
        "entrada", "orden_pendiente", "ordenes_pendientes", "inventario",
        "movimientos", "reservas", "reserva", "reportar_dano", "reportes_dano", "cancelar", "chatid",
    ]
    comandos_validacion = ["inventario", "movimientos", "reservas", "reserva", "chatid"]
    comandos_salida = ["salida", "reserva", "cancelar", "chatid"]
    # El grupo de pruebas está exento de la restricción de comando-por-grupo,
    # así que ahí sí tiene sentido mostrarlos todos juntos.
    comandos_pruebas = sorted(set(
        comandos_comercial + comandos_almacen + comandos_validacion + comandos_salida
    ))

    mapa_grupos = {
        COMERCIAL_GROUP_ID: comandos_comercial,
        ALMACEN_GROUP_ID: comandos_almacen,
        VALIDACION_GROUP_ID: comandos_validacion,
        SALIDA_GROUP_ID: comandos_salida,
        PRUEBAS_GROUP_ID: comandos_pruebas,
    }

    for grupo_id, comandos in mapa_grupos.items():
        if grupo_id is None:
            continue
        lista = [BotCommand(c, DESCRIPCIONES_COMANDOS.get(c, c)) for c in comandos]
        try:
            await application.bot.set_my_commands(lista, scope=BotCommandScopeChat(chat_id=grupo_id))
        except Exception:
            logger.exception("No pude configurar el menú de comandos para el grupo %s", grupo_id)

    comandos_admin = [
        "chatid", "autorizar", "desautorizar", "agregar_rol", "quitar_rol",
        "usuarios", "auditoria", "ajustar", "cargar_inicial",
    ]
    lista_admin = [BotCommand(c, DESCRIPCIONES_COMANDOS.get(c, c)) for c in comandos_admin]
    try:
        await application.bot.set_my_commands(lista_admin, scope=BotCommandScopeAllPrivateChats())
    except Exception:
        logger.exception("No pude configurar el menú de comandos privados.")


async def _post_init(application: Application):
    await init_schema()
    logger.info("Esquema de base de datos verificado/creado.")
    await sembrar_usuarios_fijos()
    logger.info("Usuarios fijos del código sincronizados con la tabla usuarios.")
    await _configurar_menus_comandos(application)
    logger.info("Menús de comandos configurados.")
    await precargar_lector()
    logger.info("Modelo de lectura de series (EasyOCR) precargado.")


def main():
    application = Application.builder().token(BOT_TOKEN).post_init(_post_init).build()

    # --- Guardián global (capa 1) -----------------------------------
    # Corre antes que cualquier otro handler, tanto para comandos como
    # para botones. group=-100 asegura la prioridad más alta.
    application.add_handler(MessageHandler(filters.ALL, guardian_global), group=-100)
    application.add_handler(CallbackQueryHandler(guardian_global), group=-100)

    # --- Comandos administrativos (privado, solo admin) --------------
    application.add_handler(CommandHandler("chatid", admin.chatid))
    application.add_handler(CommandHandler("autorizar", admin.autorizar))
    application.add_handler(CommandHandler("desautorizar", admin.desautorizar))
    application.add_handler(CommandHandler("agregar_rol", admin.agregar_rol))
    application.add_handler(CommandHandler("quitar_rol", admin.quitar_rol))
    application.add_handler(CommandHandler("usuarios", admin.usuarios))
    application.add_handler(CommandHandler("auditoria", admin.auditoria))
    application.add_handler(CommandHandler("ajustar", admin.ajustar))
    application.add_handler(CommandHandler("cargar_inicial", admin.cargar_inicial))

    # --- Inventario paneles (Grupo 3) y vista comercial (Grupo 1) ----
    application.add_handler(CommandHandler("inventario", inventario.inventario))
    application.add_handler(CommandHandler("disponible", inventario.disponible))
    application.add_handler(CommandHandler("movimientos", inventario.movimientos))
    application.add_handler(
        CallbackQueryHandler(
            inventario.responder_formato_callback,
            pattern="^formato:(inventario|disponible|movimientos):",
        )
    )

    # --- Reservar Paneles (Grupo 1) -----------------------------------
    application.add_handler(comercial.construir_conversation_handler())
    application.add_handler(CommandHandler("pendientes", comercial.pendientes))
    application.add_handler(CommandHandler("reservas", comercial.reservas))
    application.add_handler(CommandHandler("reserva", comercial.reserva_detalle))
    application.add_handler(
        CallbackQueryHandler(comercial.confirmar_odoo_callback, pattern="^odoo_confirmar:")
    )
    application.add_handler(
        CallbackQueryHandler(comercial.responder_formato_reservas_callback, pattern="^formato:reservas:")
    )

    # --- Entrada paneles almacén (Grupo 2) ----------------------------
    application.add_handler(almacen.construir_entrada_handler())
    application.add_handler(almacen.construir_orden_pendiente_handler())
    application.add_handler(CommandHandler("ordenes_pendientes", almacen.ordenes_pendientes))

    # --- Salidas paneles de almacén (Grupo 4) -------------------------
    application.add_handler(salida.construir_salida_handler())

    # --- Paneles dañados (Almacén y Comercial) ------------------------
    application.add_handler(danos.construir_dano_handler())
    application.add_handler(CommandHandler("reportes_dano", danos.reportes_dano))

    logger.info("Bot iniciado, esperando mensajes...")
    application.run_polling()


if __name__ == "__main__":
    main()
