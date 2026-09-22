from telegram import Update, InputFile
from telegram.ext import ContextTypes

from security.groups import requiere_grupo
from handlers.reporting import (
    construir_reporte, construir_excel, boton_excel,
    construir_reporte_movimientos, construir_excel_movimientos, boton_excel_movimientos,
)


@requiere_grupo("inventario")
async def inventario(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Vista física: Almacén e Inventario paneles."""
    resumen, _ = await construir_reporte("fisica")
    await update.message.reply_text(resumen, parse_mode="Markdown", reply_markup=boton_excel("fisica"))


@requiere_grupo("disponible")
async def disponible(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Vista comercial: incluye lo pendiente por llegar."""
    resumen, _ = await construir_reporte("comercial")
    await update.message.reply_text(resumen, parse_mode="Markdown", reply_markup=boton_excel("comercial"))


async def enviar_excel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Se dispara al tocar el botón '📊 Descargar detalle en Excel'."""
    query = update.callback_query
    await query.answer()
    vista = query.data.split(":", 1)[1]
    _, filas = await construir_reporte(vista)
    archivo = construir_excel(filas, vista)
    nombre = "inventario_almacen.xlsx" if vista == "fisica" else "disponible_comercial.xlsx"
    await query.message.reply_document(InputFile(archivo, filename=nombre))


@requiere_grupo("movimientos")
async def movimientos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entradas y salidas de almacén — historial de ordenes_compra recibidas y despachos."""
    resumen, _, _ = await construir_reporte_movimientos()
    await update.message.reply_text(
        resumen, parse_mode="Markdown", reply_markup=boton_excel_movimientos()
    )


async def enviar_excel_movimientos_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, entradas, salidas = await construir_reporte_movimientos()
    archivo = construir_excel_movimientos(entradas, salidas)
    await query.message.reply_document(InputFile(archivo, filename="movimientos_almacen.xlsx"))
