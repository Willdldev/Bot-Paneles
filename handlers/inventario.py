"""
/inventario, /disponible, /movimientos -> primero preguntan "¿en el chat
o en Excel?" y solo generan lo que la persona elija, en vez de mandar
siempre el resumen y ofrecer el Excel de una vez.
"""
from telegram import Update, InputFile
from telegram.ext import ContextTypes

from security.groups import requiere_grupo
from handlers.reporting import (
    construir_reporte, construir_excel,
    construir_reporte_movimientos, construir_excel_movimientos,
    teclado_formato,
)


@requiere_grupo("inventario")
async def inventario(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Vista física: Almacén e Inventario paneles."""
    await update.message.reply_text(
        "¿Cómo quieres ver el inventario?", reply_markup=teclado_formato("inventario")
    )


@requiere_grupo("disponible")
async def disponible(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Vista comercial: incluye lo pendiente por llegar."""
    await update.message.reply_text(
        "¿Cómo quieres ver el disponible?", reply_markup=teclado_formato("disponible")
    )


@requiere_grupo("movimientos")
async def movimientos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entradas y salidas de almacén."""
    await update.message.reply_text(
        "¿Cómo quieres ver los movimientos?", reply_markup=teclado_formato("movimientos")
    )


async def responder_formato_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Atiende el botón elegido para /inventario, /disponible y /movimientos."""
    query = update.callback_query
    await query.answer()
    _, tipo, formato = query.data.split(":")

    if tipo == "inventario":
        resumen, filas = await construir_reporte("fisica")
        if formato == "chat":
            await query.edit_message_text(resumen, parse_mode="Markdown")
        else:
            archivo = construir_excel(filas, "fisica")
            await query.edit_message_text("📊 Aquí tienes el detalle en Excel:")
            await query.message.reply_document(InputFile(archivo, filename="inventario_almacen.xlsx"))

    elif tipo == "disponible":
        resumen, filas = await construir_reporte("comercial")
        if formato == "chat":
            await query.edit_message_text(resumen, parse_mode="Markdown")
        else:
            archivo = construir_excel(filas, "comercial")
            await query.edit_message_text("📊 Aquí tienes el detalle en Excel:")
            await query.message.reply_document(InputFile(archivo, filename="disponible_comercial.xlsx"))

    elif tipo == "movimientos":
        resumen, entradas, salidas = await construir_reporte_movimientos()
        if formato == "chat":
            await query.edit_message_text(resumen, parse_mode="Markdown")
        else:
            archivo = construir_excel_movimientos(entradas, salidas)
            await query.edit_message_text("📊 Aquí tienes el historial completo en Excel:")
            await query.message.reply_document(InputFile(archivo, filename="movimientos_almacen.xlsx"))
