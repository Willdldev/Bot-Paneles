"""
Grupo 2: Entrada paneles almacén (Logística).

/entrada         -> registra la llegada física de un lote al almacén:
                     fecha, marca, modelo, potencia, cantidad, proveedor,
                     orden de compra, y si tiene asignación a proyecto.
                     Si dice que sí, pide proyecto + cantidad (puede
                     repetirse para varios proyectos) y VALIDA cada uno
                     contra las reservas reales hechas en Reservar Paneles
                     antes de dejar confirmar — porque comercial reserva
                     primero, y esto es el cuadre de esa reserva contra
                     lo que de verdad llegó.
/orden_pendiente -> registra que se colocó una orden de compra que aún no
                     ha llegado (alimenta pendiente_por_llegar, para que
                     Reservar Paneles pueda reservar contra ella).
/ordenes_pendientes -> lista lo que está pedido y todavía no ha llegado.

La entrega directa a proyecto (sin pasar por almacén) se resuelve dentro
de /salida (Grupo 4), con su propio flujo de fotos y series — no se
maneja aquí.
"""
from datetime import datetime, date

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, ConversationHandler, CommandHandler, MessageHandler, filters, CallbackQueryHandler,
)

from security.groups import requiere_grupo, requiere_rol
from db import get_pool

(
    E_FECHA, E_MARCA, E_MODELO, E_POTENCIA, E_CANTIDAD, E_PROVEEDOR, E_ORDEN,
    E_ASIGNACION, E_ASIG_PROYECTO, E_ASIG_CANTIDAD, E_ASIG_MAS, E_CONFIRMAR,
) = range(12)

(
    P_MARCA, P_MODELO, P_POTENCIA, P_CANTIDAD, P_PROVEEDOR, P_ORDEN, P_CONFIRMAR,
) = range(12, 19)


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


# ============================================================ /entrada

@requiere_grupo("entrada")
@requiere_rol("logistica", "admin")
async def entrada_inicio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["entrada"] = {}
    await update.message.reply_text(
        '¿Fecha de entrada? (escribe DD/MM/AAAA, o "hoy")\n(/cancelar para salir)'
    )
    return E_FECHA


async def entrada_fecha(update: Update, context: ContextTypes.DEFAULT_TYPE):
    fecha = _parsear_fecha(update.message.text)
    if fecha is None:
        await update.message.reply_text('No entendí esa fecha. Usa DD/MM/AAAA o escribe "hoy".')
        return E_FECHA
    context.user_data["entrada"]["fecha"] = fecha
    await update.message.reply_text("¿Marca del panel que llegó?")
    return E_MARCA


async def entrada_marca(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["entrada"]["marca"] = update.message.text.strip()
    await update.message.reply_text("¿Modelo?")
    return E_MODELO


async def entrada_modelo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["entrada"]["modelo"] = update.message.text.strip()
    await update.message.reply_text("¿Potencia en W? (solo el número, ej. 550)")
    return E_POTENCIA


async def entrada_potencia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text.strip()
    if not texto.isdigit():
        await update.message.reply_text("Escribe solo el número de potencia, ej. 550")
        return E_POTENCIA
    context.user_data["entrada"]["potencia"] = int(texto)
    await update.message.reply_text("¿Cantidad de paneles que llegaron?")
    return E_CANTIDAD


async def entrada_cantidad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text.strip()
    if not texto.isdigit() or int(texto) <= 0:
        await update.message.reply_text("Escribe un número entero mayor a 0.")
        return E_CANTIDAD
    context.user_data["entrada"]["cantidad"] = int(texto)
    await update.message.reply_text("¿Proveedor?")
    return E_PROVEEDOR


async def entrada_proveedor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["entrada"]["proveedor"] = update.message.text.strip()
    await update.message.reply_text('¿Número de orden de compra? (escribe "ninguno" si no aplica)')
    return E_ORDEN


async def entrada_orden(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["entrada"]["numero_orden"] = update.message.text.strip()
    context.user_data["entrada"]["asignaciones"] = []
    teclado = InlineKeyboardMarkup([[
        InlineKeyboardButton("Sí", callback_data="asig_si"),
        InlineKeyboardButton("No", callback_data="asig_no"),
    ]])
    await update.message.reply_text(
        "¿Esta entrada tiene alguna asignación a proyecto?", reply_markup=teclado
    )
    return E_ASIGNACION


async def entrada_asignacion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "asig_no":
        return await _armar_resumen_final(query, context.user_data["entrada"])

    await query.edit_message_text("¿Nombre del proyecto?")
    return E_ASIG_PROYECTO


async def entrada_asig_proyecto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["entrada"]["_proyecto_actual"] = update.message.text.strip()
    await update.message.reply_text("¿Cantidad reservada para ese proyecto?")
    return E_ASIG_CANTIDAD


async def entrada_asig_cantidad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text.strip()
    if not texto.isdigit() or int(texto) <= 0:
        await update.message.reply_text("Escribe un número entero mayor a 0.")
        return E_ASIG_CANTIDAD

    datos = context.user_data["entrada"]
    proyecto = datos.pop("_proyecto_actual")
    datos["asignaciones"].append({"proyecto": proyecto, "cantidad": int(texto)})

    teclado = InlineKeyboardMarkup([[
        InlineKeyboardButton("Sí", callback_data="asigmas_si"),
        InlineKeyboardButton("No", callback_data="asigmas_no"),
    ]])
    await update.message.reply_text(
        "¿Hay más proyectos con paneles reservados en esta entrada?", reply_markup=teclado
    )
    return E_ASIG_MAS


async def entrada_asig_mas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "asigmas_si":
        await query.edit_message_text("¿Nombre del siguiente proyecto?")
        return E_ASIG_PROYECTO

    return await _armar_resumen_final(query, context.user_data["entrada"])


async def _armar_resumen_final(query, datos: dict):
    """
    Compara lo que logística dijo (asignaciones) contra las reservas reales
    en la base de datos, y arma el mensaje final de confirmación con
    cualquier discrepancia visible antes de que confirmen.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        reservas_reales = await conn.fetch(
            "SELECT proyecto, cantidad FROM reservas WHERE marca ILIKE $1 AND modelo ILIKE $2 "
            "AND potencia_w = $3 AND estado_despacho != 'despachada' ORDER BY fecha_solicitud",
            datos["marca"], datos["modelo"], datos["potencia"],
        )

    asignaciones = datos.get("asignaciones", [])
    restantes = list(reservas_reales)
    lineas = []

    for asign in asignaciones:
        coincidencia = next(
            (r for r in restantes if r["proyecto"].strip().lower() == asign["proyecto"].strip().lower()),
            None,
        )
        if coincidencia is not None:
            restantes.remove(coincidencia)
            if coincidencia["cantidad"] == asign["cantidad"]:
                lineas.append(f"✅ {asign['proyecto']}: {asign['cantidad']} (coincide con la reserva)")
            else:
                lineas.append(
                    f"⚠️ {asign['proyecto']}: dijiste {asign['cantidad']}, pero la reserva "
                    f"registrada dice {coincidencia['cantidad']}"
                )
        else:
            lineas.append(f"⚠️ {asign['proyecto']}: {asign['cantidad']} — no encontré esa reserva registrada")

    if restantes:
        lineas.append("")
        lineas.append("⚠️ Reservas activas que no mencionaste:")
        for r in restantes:
            lineas.append(f"• {r['proyecto']}: {r['cantidad']}")

    if not asignaciones and reservas_reales:
        detalle = "\n".join(f"• {r['proyecto']}: {r['cantidad']}" for r in reservas_reales)
        texto_validacion = f"\n\n⚠️ Dijiste que no había asignación, pero encontré reservas activas:\n{detalle}"
    elif lineas:
        texto_validacion = "\n\n" + "\n".join(lineas)
    else:
        texto_validacion = ""

    teclado = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Confirmar entrada", callback_data="entrada_confirmar"),
        InlineKeyboardButton("❌ Cancelar", callback_data="entrada_cancelar"),
    ]])
    texto = (
        f"Vas a registrar la entrada del {datos['fecha']:%d/%m/%Y}: *{datos['cantidad']}* × "
        f"{datos['marca']} {datos['modelo']} {datos['potencia']}W — proveedor {datos['proveedor']}, "
        f"orden {datos['numero_orden']}.{texto_validacion}\n\n¿Confirmas?"
    )
    await query.edit_message_text(texto, parse_mode="Markdown", reply_markup=teclado)
    return E_CONFIRMAR


async def entrada_confirmar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "entrada_cancelar":
        await query.edit_message_text("Entrada cancelada.")
        context.user_data.pop("entrada", None)
        return ConversationHandler.END

    datos = context.user_data.get("entrada")
    if not datos:
        await query.edit_message_text("Esta entrada ya expiró, vuelve a intentar con /entrada.")
        return ConversationHandler.END

    usuario = update.effective_user
    numero_orden = datos["numero_orden"]
    sin_orden = numero_orden.lower() in ("ninguno", "n/a", "no", "-")
    fecha_dt = datetime.combine(datos["fecha"], datetime.min.time())

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Llegó físicamente: sube en_almacen y baja pendiente_por_llegar
            # (sin pasar de 0), sin tocar reservado.
            await conn.execute(
                """
                INSERT INTO paneles_stock (marca, modelo, potencia_w, en_almacen)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (marca, modelo, potencia_w) DO UPDATE
                SET en_almacen = paneles_stock.en_almacen + $4,
                    pendiente_por_llegar = GREATEST(paneles_stock.pendiente_por_llegar - $4, 0)
                """,
                datos["marca"], datos["modelo"], datos["potencia"], datos["cantidad"],
            )

            orden_existente = None
            if not sin_orden:
                orden_existente = await conn.fetchrow(
                    "SELECT id FROM ordenes_compra WHERE numero_orden = $1 AND estado = 'pendiente' "
                    "AND marca ILIKE $2 AND modelo ILIKE $3 AND potencia_w = $4",
                    numero_orden, datos["marca"], datos["modelo"], datos["potencia"],
                )

            if orden_existente:
                await conn.execute(
                    "UPDATE ordenes_compra SET estado='recibida', tipo_entrega='almacen', "
                    "fecha_recepcion=$1 WHERE id=$2",
                    fecha_dt, orden_existente["id"],
                )
            else:
                await conn.execute(
                    """
                    INSERT INTO ordenes_compra
                        (proveedor, marca, modelo, potencia_w, cantidad, numero_orden,
                         tipo_entrega, estado, registrado_por, fecha_recepcion)
                    VALUES ($1, $2, $3, $4, $5, $6, 'almacen', 'recibida', $7, $8)
                    """,
                    datos["proveedor"], datos["marca"], datos["modelo"], datos["potencia"],
                    datos["cantidad"], None if sin_orden else numero_orden, usuario.id, fecha_dt,
                )

    await query.edit_message_text(
        f"✅ Entrada registrada ({datos['fecha']:%d/%m/%Y}): {datos['cantidad']} × "
        f"{datos['marca']} {datos['modelo']} {datos['potencia']}W ya están en almacén."
    )
    context.user_data.pop("entrada", None)
    return ConversationHandler.END


async def cancelar_entrada(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("entrada", None)
    await update.message.reply_text("Entrada cancelada.")
    return ConversationHandler.END


def construir_entrada_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("entrada", entrada_inicio)],
        states={
            E_FECHA: [MessageHandler(filters.TEXT & ~filters.COMMAND, entrada_fecha)],
            E_MARCA: [MessageHandler(filters.TEXT & ~filters.COMMAND, entrada_marca)],
            E_MODELO: [MessageHandler(filters.TEXT & ~filters.COMMAND, entrada_modelo)],
            E_POTENCIA: [MessageHandler(filters.TEXT & ~filters.COMMAND, entrada_potencia)],
            E_CANTIDAD: [MessageHandler(filters.TEXT & ~filters.COMMAND, entrada_cantidad)],
            E_PROVEEDOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, entrada_proveedor)],
            E_ORDEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, entrada_orden)],
            E_ASIGNACION: [CallbackQueryHandler(entrada_asignacion, pattern="^asig_")],
            E_ASIG_PROYECTO: [MessageHandler(filters.TEXT & ~filters.COMMAND, entrada_asig_proyecto)],
            E_ASIG_CANTIDAD: [MessageHandler(filters.TEXT & ~filters.COMMAND, entrada_asig_cantidad)],
            E_ASIG_MAS: [CallbackQueryHandler(entrada_asig_mas, pattern="^asigmas_")],
            E_CONFIRMAR: [CallbackQueryHandler(entrada_confirmar, pattern="^entrada_")],
        },
        fallbacks=[CommandHandler("cancelar", cancelar_entrada)],
    )


# ===================================================== /orden_pendiente

@requiere_grupo("orden_pendiente")
@requiere_rol("logistica", "admin")
async def orden_pendiente_inicio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["orden"] = {}
    await update.message.reply_text(
        "Registrar una orden de compra que aún no ha llegado.\n"
        "¿Marca del panel?\n(/cancelar para salir)"
    )
    return P_MARCA


async def orden_marca(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["orden"]["marca"] = update.message.text.strip()
    await update.message.reply_text("¿Modelo?")
    return P_MODELO


async def orden_modelo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["orden"]["modelo"] = update.message.text.strip()
    await update.message.reply_text("¿Potencia en W?")
    return P_POTENCIA


async def orden_potencia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text.strip()
    if not texto.isdigit():
        await update.message.reply_text("Escribe solo el número de potencia, ej. 550")
        return P_POTENCIA
    context.user_data["orden"]["potencia"] = int(texto)
    await update.message.reply_text("¿Cantidad pedida?")
    return P_CANTIDAD


async def orden_cantidad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text.strip()
    if not texto.isdigit() or int(texto) <= 0:
        await update.message.reply_text("Escribe un número entero mayor a 0.")
        return P_CANTIDAD
    context.user_data["orden"]["cantidad"] = int(texto)
    await update.message.reply_text("¿Proveedor?")
    return P_PROVEEDOR


async def orden_proveedor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["orden"]["proveedor"] = update.message.text.strip()
    await update.message.reply_text("¿Número de orden de compra?")
    return P_ORDEN


async def orden_numero(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["orden"]["numero_orden"] = update.message.text.strip()
    datos = context.user_data["orden"]

    teclado = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Confirmar", callback_data="orden_confirmar"),
        InlineKeyboardButton("❌ Cancelar", callback_data="orden_cancelar"),
    ]])
    await update.message.reply_text(
        f"Vas a registrar una orden pendiente: *{datos['cantidad']}* × {datos['marca']} "
        f"{datos['modelo']} {datos['potencia']}W — proveedor {datos['proveedor']}, "
        f"orden {datos['numero_orden']}.\n\n¿Confirmas?",
        parse_mode="Markdown", reply_markup=teclado,
    )
    return P_CONFIRMAR


async def orden_confirmar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "orden_cancelar":
        await query.edit_message_text("Registro cancelado.")
        context.user_data.pop("orden", None)
        return ConversationHandler.END

    datos = context.user_data.get("orden")
    if not datos:
        await query.edit_message_text("Este registro ya expiró, intenta de nuevo con /orden_pendiente.")
        return ConversationHandler.END

    usuario = update.effective_user
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO paneles_stock (marca, modelo, potencia_w, pendiente_por_llegar)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (marca, modelo, potencia_w) DO UPDATE
                SET pendiente_por_llegar = paneles_stock.pendiente_por_llegar + $4
                """,
                datos["marca"], datos["modelo"], datos["potencia"], datos["cantidad"],
            )
            await conn.execute(
                """
                INSERT INTO ordenes_compra
                    (proveedor, marca, modelo, potencia_w, cantidad, numero_orden, estado, registrado_por)
                VALUES ($1, $2, $3, $4, $5, $6, 'pendiente', $7)
                """,
                datos["proveedor"], datos["marca"], datos["modelo"], datos["potencia"],
                datos["cantidad"], datos["numero_orden"], usuario.id,
            )

    await query.edit_message_text(
        f"✅ Orden pendiente registrada: {datos['cantidad']} × {datos['marca']} {datos['modelo']} "
        f"{datos['potencia']}W ya se pueden reservar aunque no hayan llegado."
    )
    context.user_data.pop("orden", None)
    return ConversationHandler.END


async def cancelar_orden(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("orden", None)
    await update.message.reply_text("Registro cancelado.")
    return ConversationHandler.END


def construir_orden_pendiente_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("orden_pendiente", orden_pendiente_inicio)],
        states={
            P_MARCA: [MessageHandler(filters.TEXT & ~filters.COMMAND, orden_marca)],
            P_MODELO: [MessageHandler(filters.TEXT & ~filters.COMMAND, orden_modelo)],
            P_POTENCIA: [MessageHandler(filters.TEXT & ~filters.COMMAND, orden_potencia)],
            P_CANTIDAD: [MessageHandler(filters.TEXT & ~filters.COMMAND, orden_cantidad)],
            P_PROVEEDOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, orden_proveedor)],
            P_ORDEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, orden_numero)],
            P_CONFIRMAR: [CallbackQueryHandler(orden_confirmar, pattern="^orden_")],
        },
        fallbacks=[CommandHandler("cancelar", cancelar_orden)],
    )


@requiere_grupo("ordenes_pendientes")
async def ordenes_pendientes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lista las órdenes de compra colocadas que todavía no han llegado."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        filas = await conn.fetch(
            "SELECT id, marca, modelo, potencia_w, cantidad, proveedor, numero_orden, fecha_registro "
            "FROM ordenes_compra WHERE estado = 'pendiente' ORDER BY fecha_registro"
        )
    if not filas:
        await update.message.reply_text("No hay órdenes de compra pendientes por llegar.")
        return

    lineas = ["*Órdenes de compra pendientes por llegar:*", ""]
    for f in filas:
        lineas.append(
            f"#{f['id']} — {f['cantidad']} × {f['marca']} {f['modelo']} {f['potencia_w']}W — "
            f"{f['proveedor']} (orden: {f['numero_orden'] or '—'})"
        )
    await update.message.reply_text("\n".join(lineas), parse_mode="Markdown")
