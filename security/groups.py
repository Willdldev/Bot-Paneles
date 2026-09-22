import functools

from telegram import Update
from telegram.ext import ContextTypes

from config import GRUPOS_CONFIGURADOS, COMANDOS_POR_GRUPO, PRUEBAS_GROUP_ID
from security.audit import registrar_intento
from security.auth import tiene_alguno_de


def requiere_grupo(nombre_comando: str):
    """
    Decorador para comandos de negocio (reservar, entrada, inventario, salida...).

    Capa 2: si hay grupos configurados, el chat debe estar en esa lista.
    Capa 3: el comando debe pertenecer específicamente a este grupo.
    Chat privado y PRUEBAS_GROUP_ID quedan exentos de ambas capas (pero
    la capa 1 -usuario autorizado- ya se validó en el guardián global).
    """

    def decorador(func):
        @functools.wraps(func)
        async def envoltura(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
            chat = update.effective_chat
            user = update.effective_user

            es_privado = chat.type == "private"
            es_pruebas = PRUEBAS_GROUP_ID is not None and chat.id == PRUEBAS_GROUP_ID

            if not (es_privado or es_pruebas):
                if GRUPOS_CONFIGURADOS and chat.id not in GRUPOS_CONFIGURADOS:
                    await registrar_intento(
                        user.id, user.full_name, f"/{nombre_comando}",
                        chat.id, chat.title, "bloqueado", detalle="chat no autorizado",
                    )
                    await update.message.reply_text(
                        "⛔ Este grupo no está autorizado para usar el bot."
                    )
                    return

                grupos_del_comando = COMANDOS_POR_GRUPO.get(nombre_comando, set())
                if grupos_del_comando and chat.id not in grupos_del_comando:
                    await registrar_intento(
                        user.id, user.full_name, f"/{nombre_comando}",
                        chat.id, chat.title, "bloqueado", detalle="comando no pertenece a este grupo",
                    )
                    await update.message.reply_text(
                        f"⛔ El comando /{nombre_comando} no se usa en este grupo."
                    )
                    return

            await registrar_intento(
                user.id, user.full_name, f"/{nombre_comando}", chat.id, chat.title, "autorizado"
            )
            return await func(update, context, *args, **kwargs)

        return envoltura

    return decorador


def requiere_rol(*roles_permitidos: str):
    """Decorador adicional para exigir uno de varios roles (ej. solo comercial)."""

    def decorador(func):
        @functools.wraps(func)
        async def envoltura(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
            user = update.effective_user
            if not await tiene_alguno_de(user.id, *roles_permitidos):
                await update.message.reply_text("⛔ No tienes el rol necesario para este comando.")
                return
            return await func(update, context, *args, **kwargs)

        return envoltura

    return decorador
