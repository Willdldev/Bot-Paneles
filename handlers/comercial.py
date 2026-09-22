"""
Grupo 1: Reservar Paneles (Comercial).

/reservar   -> conversación paso a paso (marca, modelo, potencia, cantidad,
               proyecto), valida contra el disponible comercial, y al
               confirmar descuenta el inventario y publica el botón de
               confirmación de Odoo para logística.
/pendientes -> reservas cuyo registro en Odoo todavía no se ha confirmado.
"""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import (
    ContextTypes, ConversationHandler, CommandHandler, MessageHandler, filters, CallbackQueryHandler,
)

from security.groups import requiere_grupo, requiere_rol
from security.auth import tiene_alguno_de
from db import get_pool
from handlers.reporting import construir_reporte_reservas, construir_excel_reservas, boton_excel_reservas

MARCA, MODELO, POTENCIA, CANTIDAD, PROYECTO, CONFIRMAR = range(6)


@requiere_grupo("reservar")
@requiere_rol("comercial", "admin")
async def reservar_inicio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["reserva"] = {}
    await update.message.reply_text("¿Marca del panel?\n(/cancelar para salir en cualquier momento)")
    return MARCA


async def recibir_marca(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["reserva"]["marca"] = update.message.text.strip()
    await update.message.reply_text("¿Modelo?")
    return MODELO


async def recibir_modelo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["reserva"]["modelo"] = update.message.text.strip()
    await update.message.reply_text("¿Potencia en W? (solo el número, ej. 550)")
    return POTENCIA


async def recibir_potencia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text.strip()
    if not texto.isdigit():
        await update.message.reply_text("Escribe solo el número de potencia, ej. 550")
        return POTENCIA
    context.user_data["reserva"]["potencia"] = int(texto)
    await update.message.reply_text("¿Cantidad de paneles a reservar?")
    return CANTIDAD


async def recibir_cantidad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text.strip()
    if not texto.isdigit() or int(texto) <= 0:
        await update.message.reply_text("Escribe un número entero mayor a 0.")
        return CANTIDAD
    context.user_data["reserva"]["cantidad"] = int(texto)
    await update.message.reply_text("¿Para qué proyecto es esta reserva?")
    return PROYECTO


async def recibir_proyecto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["reserva"]["proyecto"] = update.message.text.strip()
    datos = context.user_data["reserva"]

    pool = await get_pool()
    async with pool.acquire() as conn:
        fila = await conn.fetchrow(
            "SELECT en_almacen, pendiente_por_llegar, reservado FROM paneles_stock "
            "WHERE marca ILIKE $1 AND modelo ILIKE $2 AND potencia_w = $3",
            datos["marca"], datos["modelo"], datos["potencia"],
        )

    if fila is None:
        await update.message.reply_text(
            f"⚠️ No encontré *{datos['marca']} {datos['modelo']} {datos['potencia']}W* registrado "
            "todavía. Pídele a almacén que lo registre primero.\n\nReserva cancelada.",
            parse_mode="Markdown",
        )
        context.user_data.pop("reserva", None)
        return ConversationHandler.END

    disponible = fila["en_almacen"] + fila["pendiente_por_llegar"] - fila["reservado"]
    if datos["cantidad"] > disponible:
        await update.message.reply_text(
            f"⚠️ Solo hay {disponible} disponibles de {datos['marca']} {datos['modelo']} "
            f"{datos['potencia']}W. Escribe una cantidad menor, o /cancelar."
        )
        return CANTIDAD

    teclado = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Confirmar reserva", callback_data="reservar_confirmar"),
        InlineKeyboardButton("❌ Cancelar", callback_data="reservar_cancelar"),
    ]])
    await update.message.reply_text(
        f"Vas a reservar *{datos['cantidad']}* × {datos['marca']} {datos['modelo']} "
        f"{datos['potencia']}W para *{datos['proyecto']}*.\n\n¿Confirmas?",
        parse_mode="Markdown", reply_markup=teclado,
    )
    return CONFIRMAR


async def confirmar_reserva(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "reservar_cancelar":
        await query.edit_message_text("Reserva cancelada.")
        context.user_data.pop("reserva", None)
        return ConversationHandler.END

    datos = context.user_data.get("reserva")
    if not datos:
        await query.edit_message_text("Esta reserva ya expiró, vuelve a intentar con /reservar.")
        return ConversationHandler.END

    usuario = update.effective_user
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            # FOR UPDATE bloquea la fila para evitar que dos reservas simultáneas
            # se pasen del disponible real (condición de carrera).
            fila = await conn.fetchrow(
                "SELECT en_almacen, pendiente_por_llegar, reservado FROM paneles_stock "
                "WHERE marca ILIKE $1 AND modelo ILIKE $2 AND potencia_w = $3 FOR UPDATE",
                datos["marca"], datos["modelo"], datos["potencia"],
            )
            if fila is None:
                await query.edit_message_text("Ese registro ya no existe. Reserva cancelada.")
                context.user_data.pop("reserva", None)
                return ConversationHandler.END

            disponible = fila["en_almacen"] + fila["pendiente_por_llegar"] - fila["reservado"]
            if datos["cantidad"] > disponible:
                await query.edit_message_text(
                    f"⚠️ Ya no hay suficiente disponible (quedan {disponible}). "
                    "Reserva cancelada, intenta de nuevo con /reservar."
                )
                context.user_data.pop("reserva", None)
                return ConversationHandler.END

            await conn.execute(
                "UPDATE paneles_stock SET reservado = reservado + $1 "
                "WHERE marca ILIKE $2 AND modelo ILIKE $3 AND potencia_w = $4",
                datos["cantidad"], datos["marca"], datos["modelo"], datos["potencia"],
            )
            reserva_id = await conn.fetchval(
                """
                INSERT INTO reservas (marca, modelo, potencia_w, cantidad, proyecto, solicitado_por)
                VALUES ($1, $2, $3, $4, $5, $6) RETURNING id
                """,
                datos["marca"], datos["modelo"], datos["potencia"], datos["cantidad"],
                datos["proyecto"], usuario.id,
            )

    await query.edit_message_text(
        f"✅ Reserva #{reserva_id} creada: {datos['cantidad']} × {datos['marca']} {datos['modelo']} "
        f"{datos['potencia']}W para {datos['proyecto']}."
    )

    teclado_odoo = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Ya lo registré en Odoo", callback_data=f"odoo_confirmar:{reserva_id}")
    ]])
    mensaje_odoo = await context.bot.send_message(
        chat_id=query.message.chat_id,
        text=(
            f"📋 *Pendiente en Odoo* — Reserva #{reserva_id}\n"
            f"{datos['cantidad']} × {datos['marca']} {datos['modelo']} {datos['potencia']}W — "
            f"{datos['proyecto']}\n\nLogística: confirma aquí cuando ya lo hayas registrado en Odoo."
        ),
        parse_mode="Markdown", reply_markup=teclado_odoo,
    )

    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE reservas SET mensaje_odoo_chat_id=$1, mensaje_odoo_message_id=$2 WHERE id=$3",
            mensaje_odoo.chat_id, mensaje_odoo.message_id, reserva_id,
        )

    context.user_data.pop("reserva", None)
    return ConversationHandler.END


async def cancelar_conversacion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("reserva", None)
    await update.message.reply_text("Reserva cancelada.")
    return ConversationHandler.END


async def confirmar_odoo_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Solo logística (o admin) puede confirmar que ya se registró en Odoo."""
    query = update.callback_query
    reserva_id = int(query.data.split(":", 1)[1])

    if not await tiene_alguno_de(update.effective_user.id, "logistica", "admin"):
        await query.answer("⛔ Solo logística puede confirmar esto.", show_alert=True)
        return
    await query.answer()

    pool = await get_pool()
    async with pool.acquire() as conn:
        fila = await conn.fetchrow("SELECT estado_odoo FROM reservas WHERE id=$1", reserva_id)
        if fila is None:
            await query.edit_message_text("Esa reserva ya no existe.")
            return
        if fila["estado_odoo"] == "confirmada":
            await query.answer("Ya estaba confirmada.", show_alert=True)
            return
        await conn.execute(
            "UPDATE reservas SET estado_odoo='confirmada', confirmado_por=$1, "
            "fecha_confirmacion_odoo=now() WHERE id=$2",
            update.effective_user.id, reserva_id,
        )

    texto_actual = query.message.text or ""
    await query.edit_message_text(
        f"{texto_actual}\n\n✅ Confirmado en Odoo por {update.effective_user.full_name}.",
    )


@requiere_grupo("pendientes")
async def pendientes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = await get_pool()
    async with pool.acquire() as conn:
        filas = await conn.fetch(
            "SELECT id, marca, modelo, potencia_w, cantidad, proyecto, fecha_solicitud "
            "FROM reservas WHERE estado_odoo = 'pendiente' ORDER BY fecha_solicitud"
        )
    if not filas:
        await update.message.reply_text("No hay reservas pendientes de confirmar en Odoo. 🎉")
        return

    lineas = ["*Pendientes de registrar en Odoo:*", ""]
    for f in filas:
        lineas.append(
            f"#{f['id']} — {f['cantidad']} × {f['marca']} {f['modelo']} {f['potencia_w']}W — "
            f"{f['proyecto']} ({f['fecha_solicitud']:%d/%m %H:%M})"
        )
    await update.message.reply_text("\n".join(lineas), parse_mode="Markdown")


@requiere_grupo("reservas")
async def reservas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lista todas las reservas activas (no solo las pendientes de Odoo)."""
    resumen, _ = await construir_reporte_reservas()
    await update.message.reply_text(resumen, parse_mode="Markdown", reply_markup=boton_excel_reservas())


async def enviar_excel_reservas_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, filas = await construir_reporte_reservas()
    archivo = construir_excel_reservas(filas)
    await query.message.reply_document(InputFile(archivo, filename="reservas_activas.xlsx"))


def construir_conversation_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("reservar", reservar_inicio)],
        states={
            MARCA: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_marca)],
            MODELO: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_modelo)],
            POTENCIA: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_potencia)],
            CANTIDAD: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_cantidad)],
            PROYECTO: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_proyecto)],
            CONFIRMAR: [CallbackQueryHandler(confirmar_reserva, pattern="^reservar_")],
        },
        fallbacks=[CommandHandler("cancelar", cancelar_conversacion)],
    )
