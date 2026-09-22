"""
Reportar paneles dañados/rotos — disponible tanto en Entrada paneles
almacén como en Reservar Paneles, porque el daño se puede descubrir
desde cualquiera de los dos lados.

/reportar_dano -> marca, modelo, potencia, cantidad, si está ligado a una
                   reserva de proyecto (si sí, pide el número), y el
                   motivo. Al confirmar: resta de en_almacen y suma a
                   danados; si estaba ligado a una reserva, también resta
                   esa cantidad de reservado Y de la reserva misma (para
                   que /salida no intente despachar más de lo que
                   realmente queda sano).
/reportes_dano -> historial de reportes de daño.
"""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, ConversationHandler, CommandHandler, MessageHandler, filters, CallbackQueryHandler,
)

from security.groups import requiere_grupo
from db import get_pool

D_MARCA, D_MODELO, D_POTENCIA, D_CANTIDAD, D_RESERVA_SINO, D_RESERVA_ID, D_MOTIVO, D_CONFIRMAR = range(8)


@requiere_grupo("reportar_dano")
async def dano_inicio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["dano"] = {}
    await update.message.reply_text("¿Marca del panel dañado?\n(/cancelar para salir)")
    return D_MARCA


async def dano_marca(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["dano"]["marca"] = update.message.text.strip()
    await update.message.reply_text("¿Modelo?")
    return D_MODELO


async def dano_modelo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["dano"]["modelo"] = update.message.text.strip()
    await update.message.reply_text("¿Potencia en W?")
    return D_POTENCIA


async def dano_potencia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text.strip()
    if not texto.isdigit():
        await update.message.reply_text("Escribe solo el número de potencia, ej. 550")
        return D_POTENCIA
    context.user_data["dano"]["potencia"] = int(texto)
    await update.message.reply_text("¿Cuántos paneles están dañados?")
    return D_CANTIDAD


async def dano_cantidad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text.strip()
    if not texto.isdigit() or int(texto) <= 0:
        await update.message.reply_text("Escribe un número entero mayor a 0.")
        return D_CANTIDAD
    context.user_data["dano"]["cantidad"] = int(texto)

    teclado = InlineKeyboardMarkup([[
        InlineKeyboardButton("Sí", callback_data="dres_si"),
        InlineKeyboardButton("No", callback_data="dres_no"),
    ]])
    await update.message.reply_text("¿Está ligado a una reserva de proyecto?", reply_markup=teclado)
    return D_RESERVA_SINO


async def dano_reserva_sino(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "dres_no":
        context.user_data["dano"]["reserva_id"] = None
        await query.edit_message_text("¿Cuál es el motivo? (breve descripción)")
        return D_MOTIVO

    await query.edit_message_text("¿Número de reserva? (revisa con /reservas)")
    return D_RESERVA_ID


async def dano_reserva_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text.strip()
    if not texto.isdigit():
        await update.message.reply_text("Escribe solo el número de la reserva, ej. 12")
        return D_RESERVA_ID

    datos = context.user_data["dano"]
    pool = await get_pool()
    async with pool.acquire() as conn:
        reserva = await conn.fetchrow(
            "SELECT id, cantidad, proyecto FROM reservas WHERE id = $1 AND marca ILIKE $2 "
            "AND modelo ILIKE $3 AND potencia_w = $4 AND estado_despacho != 'despachada'",
            int(texto), datos["marca"], datos["modelo"], datos["potencia"],
        )

    if reserva is None:
        await update.message.reply_text(
            "No encontré esa reserva activa para esta marca/modelo/potencia. Revisa el número con "
            "/reservas, o escribe /cancelar."
        )
        return D_RESERVA_ID

    if datos["cantidad"] > reserva["cantidad"]:
        await update.message.reply_text(
            f"⚠️ Dijiste {datos['cantidad']} dañados, pero esa reserva es de solo {reserva['cantidad']}. "
            "Escribe el número de reserva correcto, o /cancelar."
        )
        return D_RESERVA_ID

    datos["reserva_id"] = reserva["id"]
    datos["_reserva_proyecto"] = reserva["proyecto"]
    await update.message.reply_text("¿Cuál es el motivo? (breve descripción)")
    return D_MOTIVO


async def dano_motivo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    datos = context.user_data["dano"]
    datos["motivo"] = update.message.text.strip()

    reserva_txt = (
        f" — reserva #{datos['reserva_id']} ({datos.get('_reserva_proyecto')})"
        if datos.get("reserva_id") else " — sin reserva vinculada"
    )
    teclado = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Confirmar", callback_data="dano_confirmar"),
        InlineKeyboardButton("❌ Cancelar", callback_data="dano_cancelar"),
    ]])
    await update.message.reply_text(
        f"Vas a reportar *{datos['cantidad']}* × {datos['marca']} {datos['modelo']} "
        f"{datos['potencia']}W como dañados{reserva_txt}.\nMotivo: {datos['motivo']}\n\n¿Confirmas?",
        parse_mode="Markdown", reply_markup=teclado,
    )
    return D_CONFIRMAR


async def dano_confirmar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "dano_cancelar":
        await query.edit_message_text("Reporte cancelado.")
        context.user_data.pop("dano", None)
        return ConversationHandler.END

    datos = context.user_data.get("dano")
    if not datos:
        await query.edit_message_text("Este reporte ya expiró, vuelve a intentar con /reportar_dano.")
        return ConversationHandler.END

    usuario = update.effective_user
    marca, modelo, potencia, cantidad = datos["marca"], datos["modelo"], datos["potencia"], datos["cantidad"]

    pool = await get_pool()
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                fila_stock = await conn.fetchrow(
                    "SELECT en_almacen FROM paneles_stock WHERE marca ILIKE $1 AND modelo ILIKE $2 "
                    "AND potencia_w = $3 FOR UPDATE",
                    marca, modelo, potencia,
                )
                if fila_stock is None or fila_stock["en_almacen"] < cantidad:
                    disponible_fisico = fila_stock["en_almacen"] if fila_stock else 0
                    await query.edit_message_text(
                        f"⚠️ Solo hay {disponible_fisico} en almacén, no se pueden reportar {cantidad} "
                        "como dañados. Reporte cancelado, verifica el inventario."
                    )
                    context.user_data.pop("dano", None)
                    return ConversationHandler.END

                await conn.execute(
                    "UPDATE paneles_stock SET en_almacen = en_almacen - $1, danados = danados + $1 "
                    "WHERE marca ILIKE $2 AND modelo ILIKE $3 AND potencia_w = $4",
                    cantidad, marca, modelo, potencia,
                )

                reserva_id = datos.get("reserva_id")
                if reserva_id:
                    reserva_fila = await conn.fetchrow(
                        "SELECT cantidad, estado_despacho FROM reservas WHERE id = $1 FOR UPDATE", reserva_id
                    )
                    if reserva_fila is None or reserva_fila["estado_despacho"] == "despachada":
                        await query.edit_message_text(
                            "⚠️ Esa reserva ya no está disponible (puede que ya se haya despachado). "
                            "Reporte cancelado."
                        )
                        context.user_data.pop("dano", None)
                        return ConversationHandler.END
                    if cantidad > reserva_fila["cantidad"]:
                        await query.edit_message_text(
                            f"⚠️ Esa reserva ya solo tiene {reserva_fila['cantidad']} (alguien la cambió "
                            "mientras confirmabas). Reporte cancelado, intenta de nuevo."
                        )
                        context.user_data.pop("dano", None)
                        return ConversationHandler.END

                    await conn.execute(
                        "UPDATE paneles_stock SET reservado = GREATEST(reservado - $1, 0) "
                        "WHERE marca ILIKE $2 AND modelo ILIKE $3 AND potencia_w = $4",
                        cantidad, marca, modelo, potencia,
                    )
                    await conn.execute(
                        "UPDATE reservas SET cantidad = cantidad - $1 WHERE id = $2", cantidad, reserva_id
                    )

                await conn.execute(
                    """
                    INSERT INTO reportes_dano (marca, modelo, potencia_w, cantidad, reserva_id, motivo, reportado_por)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    """,
                    marca, modelo, potencia, cantidad, reserva_id, datos["motivo"], usuario.id,
                )
    except Exception:
        await query.edit_message_text(
            "⚠️ Ocurrió un error guardando el reporte. Nada se descontó del inventario. "
            "Intenta de nuevo con /reportar_dano."
        )
        context.user_data.pop("dano", None)
        return ConversationHandler.END

    aviso_reserva = ""
    if datos.get("reserva_id"):
        aviso_reserva = (
            f"\n\nLa reserva #{datos['reserva_id']} quedó reducida en {cantidad}. Si el proyecto necesita "
            "reponerlos, hay que crear una reserva nueva por esa cantidad."
        )
    await query.edit_message_text(
        f"✅ Reportado: {cantidad} × {marca} {modelo} {potencia}W dañados.\nMotivo: {datos['motivo']}"
        f"{aviso_reserva}"
    )
    context.user_data.pop("dano", None)
    return ConversationHandler.END


async def cancelar_dano(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("dano", None)
    await update.message.reply_text("Reporte cancelado.")
    return ConversationHandler.END


def construir_dano_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("reportar_dano", dano_inicio)],
        states={
            D_MARCA: [MessageHandler(filters.TEXT & ~filters.COMMAND, dano_marca)],
            D_MODELO: [MessageHandler(filters.TEXT & ~filters.COMMAND, dano_modelo)],
            D_POTENCIA: [MessageHandler(filters.TEXT & ~filters.COMMAND, dano_potencia)],
            D_CANTIDAD: [MessageHandler(filters.TEXT & ~filters.COMMAND, dano_cantidad)],
            D_RESERVA_SINO: [CallbackQueryHandler(dano_reserva_sino, pattern="^dres_")],
            D_RESERVA_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, dano_reserva_id)],
            D_MOTIVO: [MessageHandler(filters.TEXT & ~filters.COMMAND, dano_motivo)],
            D_CONFIRMAR: [CallbackQueryHandler(dano_confirmar, pattern="^dano_")],
        },
        fallbacks=[CommandHandler("cancelar", cancelar_dano)],
    )


@requiere_grupo("reportes_dano")
async def reportes_dano(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = await get_pool()
    async with pool.acquire() as conn:
        filas = await conn.fetch(
            "SELECT id, marca, modelo, potencia_w, cantidad, reserva_id, motivo, fecha "
            "FROM reportes_dano ORDER BY fecha DESC LIMIT 30"
        )
    if not filas:
        await update.message.reply_text("No hay reportes de daño registrados.")
        return

    lineas = ["*Últimos reportes de daño:*", ""]
    for f in filas:
        reserva_txt = f" (reserva #{f['reserva_id']})" if f["reserva_id"] else ""
        lineas.append(
            f"#{f['id']} — {f['cantidad']} × {f['marca']} {f['modelo']} {f['potencia_w']}W{reserva_txt} — "
            f"{f['motivo']} ({f['fecha']:%d/%m/%Y})"
        )
    await update.message.reply_text("\n".join(lineas), parse_mode="Markdown")
