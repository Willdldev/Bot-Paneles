"""
Grupo 4: Salidas paneles de almacén (Logística).

/salida pregunta, en orden: fecha de salida, marca, modelo, potencia,
cantidad y destino. Con el destino, busca automáticamente si hay una
reserva activa para esa marca+modelo+potencia+proyecto (igual que hace
/entrada) — si la hay, esta salida se descuenta de esa reserva
(reservado); si no, se descuenta directo del disponible.

Después pregunta tipo (almacén / entrega directa) y origen de compra
(local / internacional / desconocido), muestra un resumen completo de
todo lo capturado, y ahí pide las fotos de las series. Cada foto se lee
con OCR (Tesseract), validando que no se repitan ni en el lote actual ni
en el historial completo, hasta juntar exactamente la cantidad
declarada. Si la lectura automática falla, se puede escribir la serie
como texto.

Al confirmar:
- tipo='almacen'  -> descuenta en_almacen (y reservado, si venía de una
                      reserva) y marca la reserva como despachada.
- tipo='directa'  -> nunca tocó en_almacen; descuenta pendiente_por_llegar
                      (y reservado, si aplica).
Las series quedan guardadas para el historial de garantía.
"""
import logging
from datetime import datetime, date

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, ConversationHandler, CommandHandler, MessageHandler, filters, CallbackQueryHandler,
)

from security.groups import requiere_grupo, requiere_rol
from db import get_pool
from handlers.ocr import extraer_serie

logger = logging.getLogger(__name__)

(
    S_FECHA, S_MARCA, S_MODELO, S_POTENCIA, S_CANTIDAD, S_DESTINO,
    S_RESERVA_CONFIRMA, S_RESERVA_ELEGIR, S_TIPO, S_DIRECTA_PROVEEDOR, S_DIRECTA_ORDEN,
    S_ORIGEN, S_FOTOS, S_CONFIRMAR,
) = range(14)

_TECLADO_TIPO = InlineKeyboardMarkup([[
    InlineKeyboardButton("Sale de almacén", callback_data="stipo_almacen"),
    InlineKeyboardButton("Entrega directa", callback_data="stipo_directa"),
]])


def _parsear_fecha(texto: str) -> date | None:
    texto = texto.strip().lower()
    if texto in ("hoy", "today"):
        return date.today()
    for formato in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(texto, formato).date()
        except ValueError:
            continue
    return None


@requiere_grupo("salida")
@requiere_rol("logistica", "admin")
async def salida_inicio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["salida"] = {}
    await update.message.reply_text(
        '¿Fecha de salida? (escribe DD/MM/AAAA, o "hoy")\n(/cancelar para salir)'
    )
    return S_FECHA


async def salida_fecha(update: Update, context: ContextTypes.DEFAULT_TYPE):
    fecha = _parsear_fecha(update.message.text)
    if fecha is None:
        await update.message.reply_text('No entendí esa fecha. Usa DD/MM/AAAA o escribe "hoy".')
        return S_FECHA
    context.user_data["salida"]["fecha"] = fecha
    await update.message.reply_text("¿Marca del panel?")
    return S_MARCA


async def salida_marca(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["salida"]["marca"] = update.message.text.strip()
    await update.message.reply_text("¿Modelo?")
    return S_MODELO


async def salida_modelo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["salida"]["modelo"] = update.message.text.strip()
    await update.message.reply_text("¿Potencia en W?")
    return S_POTENCIA


async def salida_potencia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text.strip()
    if not texto.isdigit():
        await update.message.reply_text("Escribe solo el número de potencia, ej. 550")
        return S_POTENCIA
    context.user_data["salida"]["potencia"] = int(texto)
    await update.message.reply_text("¿Cantidad a despachar?")
    return S_CANTIDAD


async def salida_cantidad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text.strip()
    if not texto.isdigit() or int(texto) <= 0:
        await update.message.reply_text("Escribe un número entero mayor a 0.")
        return S_CANTIDAD
    context.user_data["salida"]["cantidad"] = int(texto)
    await update.message.reply_text("¿Hacia dónde va (destino / proyecto)?")
    return S_DESTINO


async def salida_destino(update: Update, context: ContextTypes.DEFAULT_TYPE):
    datos = context.user_data["salida"]
    datos["destino"] = update.message.text.strip()

    pool = await get_pool()
    async with pool.acquire() as conn:
        candidatas = await conn.fetch(
            "SELECT id, cantidad FROM reservas WHERE marca ILIKE $1 AND modelo ILIKE $2 "
            "AND potencia_w = $3 AND proyecto ILIKE $4 AND estado_despacho != 'despachada'",
            datos["marca"], datos["modelo"], datos["potencia"], datos["destino"],
        )

    if not candidatas:
        datos["reserva_id"] = None
        await update.message.reply_text(
            "No encontré una reserva activa para este destino con esa marca/modelo/potencia — "
            "se descontará directo del disponible."
        )
        await update.message.reply_text("¿Sale de almacén o es entrega directa?", reply_markup=_TECLADO_TIPO)
        return S_TIPO

    if len(candidatas) == 1:
        reserva = candidatas[0]
        datos["_reserva_candidata"] = reserva["id"]
        teclado = InlineKeyboardMarkup([[
            InlineKeyboardButton("Sí", callback_data="sresc_si"),
            InlineKeyboardButton("No", callback_data="sresc_no"),
        ]])
        await update.message.reply_text(
            f"Encontré la reserva #{reserva['id']} activa para este destino ({reserva['cantidad']} "
            "paneles). ¿Esta salida corresponde a esa reserva?",
            reply_markup=teclado,
        )
        return S_RESERVA_CONFIRMA

    detalle = "\n".join(f"#{r['id']}: {r['cantidad']}" for r in candidatas)
    await update.message.reply_text(
        f"Encontré varias reservas activas para este destino:\n{detalle}\n\n"
        'Escribe el número de la que corresponde, o escribe "ninguna".'
    )
    return S_RESERVA_ELEGIR


async def salida_reserva_confirma(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    datos = context.user_data["salida"]

    if query.data == "sresc_si":
        datos["reserva_id"] = datos.pop("_reserva_candidata")
    else:
        datos.pop("_reserva_candidata", None)
        datos["reserva_id"] = None

    await query.edit_message_text("¿Sale de almacén o es entrega directa?", reply_markup=_TECLADO_TIPO)
    return S_TIPO


async def salida_reserva_elegir(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text.strip().lower()
    datos = context.user_data["salida"]

    if texto == "ninguna":
        datos["reserva_id"] = None
    elif texto.isdigit():
        pool = await get_pool()
        async with pool.acquire() as conn:
            fila = await conn.fetchrow(
                "SELECT id FROM reservas WHERE id = $1 AND marca ILIKE $2 AND modelo ILIKE $3 "
                "AND potencia_w = $4 AND proyecto ILIKE $5 AND estado_despacho != 'despachada'",
                int(texto), datos["marca"], datos["modelo"], datos["potencia"], datos["destino"],
            )
        if fila is None:
            await update.message.reply_text("Ese número no es una de las reservas mostradas. Intenta de nuevo.")
            return S_RESERVA_ELEGIR
        datos["reserva_id"] = fila["id"]
    else:
        await update.message.reply_text('Escribe el número de la reserva, o "ninguna".')
        return S_RESERVA_ELEGIR

    await update.message.reply_text("¿Sale de almacén o es entrega directa?", reply_markup=_TECLADO_TIPO)
    return S_TIPO


_TECLADO_ORIGEN = InlineKeyboardMarkup([[
    InlineKeyboardButton("Local", callback_data="sorigen_local"),
    InlineKeyboardButton("Internacional", callback_data="sorigen_internacional"),
    InlineKeyboardButton("Desconocido", callback_data="sorigen_desconocido"),
]])


async def salida_tipo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    datos = context.user_data["salida"]
    datos["tipo"] = "almacen" if query.data == "stipo_almacen" else "directa"

    if datos["tipo"] == "directa":
        # Como esto nunca pasó por /entrada, aquí es donde se captura la
        # orden de compra — si no, esta compra quedaría sin registro.
        await query.edit_message_text("¿Proveedor de esta compra?")
        return S_DIRECTA_PROVEEDOR

    await query.edit_message_text(
        "¿La compra de origen es local, internacional, o desconocida?", reply_markup=_TECLADO_ORIGEN
    )
    return S_ORIGEN


async def salida_directa_proveedor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["salida"]["proveedor"] = update.message.text.strip()
    await update.message.reply_text('¿Número de orden de compra? (escribe "ninguno" si no aplica)')
    return S_DIRECTA_ORDEN


async def salida_directa_orden(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["salida"]["numero_orden"] = update.message.text.strip()
    await update.message.reply_text(
        "¿La compra de origen es local, internacional, o desconocida?", reply_markup=_TECLADO_ORIGEN
    )
    return S_ORIGEN


async def salida_origen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    datos = context.user_data["salida"]
    datos["origen"] = query.data.split("_", 1)[1]
    datos["series"] = []

    reserva_txt = f" (reserva #{datos['reserva_id']})" if datos.get("reserva_id") else " (sin reserva vinculada)"
    tipo_txt = "almacén" if datos["tipo"] == "almacen" else "entrega directa"
    compra_txt = (
        f"\nProveedor: {datos['proveedor']} — orden: {datos['numero_orden']}"
        if datos["tipo"] == "directa" else ""
    )
    await query.edit_message_text(
        "📋 Resumen de la salida:\n"
        f"Fecha: {datos['fecha']:%d/%m/%Y}\n"
        f"Panel: {datos['marca']} {datos['modelo']} {datos['potencia']}W\n"
        f"Cantidad: {datos['cantidad']}\n"
        f"Destino: {datos['destino']}{reserva_txt}\n"
        f"Tipo: {tipo_txt}{compra_txt}\n"
        f"Origen de compra: {datos['origen']}\n\n"
        f"Ahora envía las {datos['cantidad']} fotos de las series (una por foto). "
        "Te aviso cada una a medida que las voy leyendo.\nCuando termines, escribe /listo."
    )
    return S_FOTOS


async def _procesar_nuevo_serial(update: Update, context: ContextTypes.DEFAULT_TYPE, serial: str) -> int:
    """Valida (duplicado en el lote actual o en el historial) y agrega un
    serial ya extraído. Responde con el progreso o con la lista final."""
    datos = context.user_data["salida"]
    cantidad_objetivo = datos["cantidad"]

    if serial in datos["series"]:
        await update.message.reply_text(
            f"⚠️ La serie {serial} ya la mandaste en esta misma salida. Verifica y manda la correcta."
        )
        return S_FOTOS

    pool = await get_pool()
    async with pool.acquire() as conn:
        ya_existe = await conn.fetchrow("SELECT despacho_id FROM series_panel WHERE serial = $1", serial)

    if ya_existe:
        await update.message.reply_text(
            f"⚠️ La serie {serial} ya fue registrada antes en otro despacho. Verifica el panel."
        )
        return S_FOTOS

    datos["series"].append(serial)
    faltan = cantidad_objetivo - len(datos["series"])

    if faltan > 0:
        await update.message.reply_text(
            f"✅ Serie registrada: {serial} ({len(datos['series'])}/{cantidad_objetivo})"
        )
    else:
        lista_series = "\n".join(datos["series"])
        await update.message.reply_text(
            f"✅ Serie registrada: {serial} ({len(datos['series'])}/{cantidad_objetivo})\n\n"
            f"Ya tienes las {cantidad_objetivo} series:\n{lista_series}\n\nEscribe /listo para continuar."
        )
    return S_FOTOS


async def salida_foto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    datos = context.user_data["salida"]
    cantidad_objetivo = datos["cantidad"]

    if len(datos["series"]) >= cantidad_objetivo:
        await update.message.reply_text(
            f"Ya tienes las {cantidad_objetivo} series necesarias. Escribe /listo para continuar."
        )
        return S_FOTOS

    foto = update.message.photo[-1]
    archivo = await context.bot.get_file(foto.file_id)
    imagen_bytes = bytes(await archivo.download_as_bytearray())

    serial = await extraer_serie(imagen_bytes)

    if serial is None:
        await update.message.reply_text(
            "⚠️ No pude leer la serie en esta foto. Tómala de nuevo (más cerca, buena luz, bien "
            "enfocada), o si sigue fallando, escríbela directamente como mensaje de texto."
        )
        return S_FOTOS

    return await _procesar_nuevo_serial(update, context, serial)


async def salida_texto_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Escape para cuando la lectura automática falla: escribir la serie a mano."""
    datos = context.user_data["salida"]
    if len(datos["series"]) >= datos["cantidad"]:
        await update.message.reply_text(
            f"Ya tienes las {datos['cantidad']} series necesarias. Escribe /listo para continuar."
        )
        return S_FOTOS

    serial = update.message.text.strip().upper()
    if len(serial) < 4:
        await update.message.reply_text(
            "Eso no parece una serie válida. Manda la foto, o escribe la serie completa como texto."
        )
        return S_FOTOS

    return await _procesar_nuevo_serial(update, context, serial)


async def salida_listo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    datos = context.user_data["salida"]
    cantidad_objetivo = datos["cantidad"]
    obtenidas = len(datos.get("series", []))

    if obtenidas < cantidad_objetivo:
        await update.message.reply_text(
            f"Van {obtenidas} de {cantidad_objetivo} series. Faltan {cantidad_objetivo - obtenidas}, "
            "sigue enviando fotos."
        )
        return S_FOTOS

    lista_series = "\n".join(datos["series"])
    teclado = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Confirmar despacho", callback_data="salida_confirmar"),
        InlineKeyboardButton("❌ Cancelar", callback_data="salida_cancelar"),
    ]])
    reserva_txt = f" (reserva #{datos['reserva_id']})" if datos.get("reserva_id") else ""
    await update.message.reply_text(
        f"Vas a despachar *{cantidad_objetivo}* × {datos['marca']} {datos['modelo']} "
        f"{datos['potencia']}W hacia *{datos['destino']}*{reserva_txt}.\n\nSeries:\n{lista_series}\n\n¿Confirmas?",
        parse_mode="Markdown", reply_markup=teclado,
    )
    return S_CONFIRMAR


async def salida_confirmar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "salida_cancelar":
        await query.edit_message_text("Salida cancelada.")
        context.user_data.pop("salida", None)
        return ConversationHandler.END

    datos = context.user_data.get("salida")
    if not datos:
        await query.edit_message_text("Esta salida ya expiró, vuelve a intentar con /salida.")
        return ConversationHandler.END

    usuario = update.effective_user
    marca, modelo, potencia = datos["marca"], datos["modelo"], datos["potencia"]
    cantidad = datos["cantidad"]
    fecha_dt = datetime.combine(datos["fecha"], datetime.min.time())

    pool = await get_pool()
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                fila_stock = await conn.fetchrow(
                    "SELECT en_almacen, pendiente_por_llegar, reservado FROM paneles_stock "
                    "WHERE marca ILIKE $1 AND modelo ILIKE $2 AND potencia_w = $3 FOR UPDATE",
                    marca, modelo, potencia,
                )
                if fila_stock is None:
                    await query.edit_message_text("Ese registro de stock ya no existe. Salida cancelada.")
                    context.user_data.pop("salida", None)
                    return ConversationHandler.END

                if datos["tipo"] == "almacen":
                    if fila_stock["en_almacen"] < cantidad:
                        await query.edit_message_text(
                            f"⚠️ Solo hay {fila_stock['en_almacen']} en almacén, no {cantidad}. "
                            "Salida cancelada, verifica el inventario."
                        )
                        context.user_data.pop("salida", None)
                        return ConversationHandler.END
                    await conn.execute(
                        "UPDATE paneles_stock SET en_almacen = en_almacen - $1 "
                        "WHERE marca ILIKE $2 AND modelo ILIKE $3 AND potencia_w = $4",
                        cantidad, marca, modelo, potencia,
                    )
                else:  # entrega directa: nunca tocó en_almacen
                    await conn.execute(
                        "UPDATE paneles_stock SET pendiente_por_llegar = GREATEST(pendiente_por_llegar - $1, 0) "
                        "WHERE marca ILIKE $2 AND modelo ILIKE $3 AND potencia_w = $4",
                        cantidad, marca, modelo, potencia,
                    )
                    # Como esto nunca pasa por /entrada, aquí es donde queda el
                    # registro de la compra — si no, esta orden no aparecería
                    # en ningún lado.
                    numero_orden = datos["numero_orden"]
                    sin_orden = numero_orden.lower() in ("ninguno", "n/a", "no", "-")
                    await conn.execute(
                        """
                        INSERT INTO ordenes_compra
                            (proveedor, marca, modelo, potencia_w, cantidad, numero_orden,
                             tipo_entrega, estado, proyecto, registrado_por, fecha_recepcion)
                        VALUES ($1, $2, $3, $4, $5, $6, 'directa', 'recibida', $7, $8, $9)
                        """,
                        datos["proveedor"], marca, modelo, potencia, cantidad,
                        None if sin_orden else numero_orden, datos["destino"], usuario.id, fecha_dt,
                    )

                reserva_id = datos.get("reserva_id")
                if reserva_id:
                    reserva_fila = await conn.fetchrow(
                        "SELECT estado_despacho FROM reservas WHERE id = $1 FOR UPDATE", reserva_id
                    )
                    if reserva_fila is None or reserva_fila["estado_despacho"] == "despachada":
                        await query.edit_message_text(
                            "⚠️ Esa reserva ya no está disponible (puede que ya se haya despachado). "
                            "Salida cancelada."
                        )
                        context.user_data.pop("salida", None)
                        return ConversationHandler.END
                    await conn.execute(
                        "UPDATE paneles_stock SET reservado = GREATEST(reservado - $1, 0) "
                        "WHERE marca ILIKE $2 AND modelo ILIKE $3 AND potencia_w = $4",
                        cantidad, marca, modelo, potencia,
                    )
                    await conn.execute(
                        "UPDATE reservas SET estado_despacho = 'despachada' WHERE id = $1", reserva_id
                    )

                despacho_id = await conn.fetchval(
                    """
                    INSERT INTO despachos
                        (reserva_id, tipo, destino, marca, modelo, potencia_w, cantidad_declarada,
                         origen_compra, registrado_por, confirmado, fecha)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, true, $10)
                    RETURNING id
                    """,
                    reserva_id, datos["tipo"], datos["destino"], marca, modelo, potencia,
                    cantidad, datos["origen"], usuario.id, fecha_dt,
                )

                for serial in datos["series"]:
                    await conn.execute(
                        """
                        INSERT INTO series_panel (serial, despacho_id, marca, modelo, potencia_w)
                        VALUES ($1, $2, $3, $4, $5)
                        """,
                        serial, despacho_id, marca, modelo, potencia,
                    )
    except Exception:
        logger.exception("Fallo confirmando la salida (reserva=%s)", datos.get("reserva_id"))
        await query.edit_message_text(
            "⚠️ Ocurrió un error guardando el despacho (puede que alguna serie ya exista). "
            "Nada se descontó del inventario. Intenta de nuevo con /salida."
        )
        context.user_data.pop("salida", None)
        return ConversationHandler.END

    lista_series = "\n".join(datos["series"])
    await query.edit_message_text(
        f"✅ Despacho #{despacho_id} confirmado ({datos['fecha']:%d/%m/%Y}): "
        f"{cantidad} × {marca} {modelo} {potencia}W → {datos['destino']}.\n\n"
        f"Series registradas:\n{lista_series}"
    )
    context.user_data.pop("salida", None)
    return ConversationHandler.END


async def cancelar_salida(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("salida", None)
    await update.message.reply_text("Salida cancelada.")
    return ConversationHandler.END


def construir_salida_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("salida", salida_inicio)],
        states={
            S_FECHA: [MessageHandler(filters.TEXT & ~filters.COMMAND, salida_fecha)],
            S_MARCA: [MessageHandler(filters.TEXT & ~filters.COMMAND, salida_marca)],
            S_MODELO: [MessageHandler(filters.TEXT & ~filters.COMMAND, salida_modelo)],
            S_POTENCIA: [MessageHandler(filters.TEXT & ~filters.COMMAND, salida_potencia)],
            S_CANTIDAD: [MessageHandler(filters.TEXT & ~filters.COMMAND, salida_cantidad)],
            S_DESTINO: [MessageHandler(filters.TEXT & ~filters.COMMAND, salida_destino)],
            S_RESERVA_CONFIRMA: [CallbackQueryHandler(salida_reserva_confirma, pattern="^sresc_")],
            S_RESERVA_ELEGIR: [MessageHandler(filters.TEXT & ~filters.COMMAND, salida_reserva_elegir)],
            S_TIPO: [CallbackQueryHandler(salida_tipo, pattern="^stipo_")],
            S_DIRECTA_PROVEEDOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, salida_directa_proveedor)],
            S_DIRECTA_ORDEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, salida_directa_orden)],
            S_ORIGEN: [CallbackQueryHandler(salida_origen, pattern="^sorigen_")],
            S_FOTOS: [
                MessageHandler(filters.PHOTO, salida_foto),
                CommandHandler("listo", salida_listo),
                MessageHandler(filters.TEXT & ~filters.COMMAND, salida_texto_manual),
            ],
            S_CONFIRMAR: [CallbackQueryHandler(salida_confirmar, pattern="^salida_")],
        },
        fallbacks=[CommandHandler("cancelar", cancelar_salida)],
    )
