import logging

from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters

from config import BOT_TOKEN
from db import init_schema
from security.guardian import guardian_global
from handlers import admin, inventario, comercial, almacen, salida, danos

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def _post_init(application: Application):
    await init_schema()
    logger.info("Esquema de base de datos verificado/creado.")


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

    # --- Inventario paneles (Grupo 3) y vista comercial (Grupo 1) ----
    application.add_handler(CommandHandler("inventario", inventario.inventario))
    application.add_handler(CommandHandler("disponible", inventario.disponible))
    application.add_handler(
        CallbackQueryHandler(inventario.enviar_excel_callback, pattern="^excel:")
    )
    application.add_handler(CommandHandler("movimientos", inventario.movimientos))
    application.add_handler(
        CallbackQueryHandler(inventario.enviar_excel_movimientos_callback, pattern="^excel_movimientos$")
    )

    # --- Reservar Paneles (Grupo 1) -----------------------------------
    application.add_handler(comercial.construir_conversation_handler())
    application.add_handler(CommandHandler("pendientes", comercial.pendientes))
    application.add_handler(CommandHandler("reservas", comercial.reservas))
    application.add_handler(
        CallbackQueryHandler(comercial.confirmar_odoo_callback, pattern="^odoo_confirmar:")
    )
    application.add_handler(
        CallbackQueryHandler(comercial.enviar_excel_reservas_callback, pattern="^excel_reservas$")
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
