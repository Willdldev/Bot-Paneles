import logging

from telegram import Update
from telegram.ext import ContextTypes, ApplicationHandlerStop

from security.auth import esta_autorizado
from security.audit import registrar_intento

logger = logging.getLogger(__name__)


async def guardian_global(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Se registra en el grupo de prioridad más alta (-100) para correr antes
    que cualquier otro handler. Si la persona no está autorizada, detiene
    el procesamiento por completo con ApplicationHandlerStop — no hay
    forma de sortear esto ni con comandos ni con botones.

    Deja pasar sin revisar los mensajes de texto normales (no comandos),
    para no interferir con la conversación normal de los grupos.
    """
    user = update.effective_user
    chat = update.effective_chat
    if user is None:
        return

    es_comando = bool(
        update.message and update.message.text and update.message.text.startswith("/")
    )
    es_boton = update.callback_query is not None

    if not es_comando and not es_boton:
        return  # texto normal de grupo, no es una acción del bot

    if es_comando and update.message.text.strip().split()[0].startswith("/chatid"):
        return  # único comando abierto, sin autorización previa

    autorizado = await esta_autorizado(user.id)

    if autorizado:
        return  # deja seguir a los handlers normales

    comando = (
        update.message.text if es_comando else f"callback:{update.callback_query.data}"
    )

    await registrar_intento(
        telegram_id=user.id,
        nombre=user.full_name,
        comando=comando,
        chat_id=chat.id if chat else None,
        chat_nombre=chat.title if chat else None,
        resultado="bloqueado",
    )

    if es_comando:
        await update.message.reply_text("⛔ No estás autorizado para usar este bot.")
    else:
        await update.callback_query.answer(
            "⛔ No estás autorizado para usar este bot.", show_alert=True
        )

    raise ApplicationHandlerStop
