from telegram import Update
from telegram.ext import ContextTypes

from config import ADMINISTRADORES, USUARIOS_PERMITIDOS_FIJOS
from db import get_pool
from security.audit import registrar_intento


def _solo_privado(func):
    async def envoltura(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if update.effective_chat.type != "private":
            await update.message.reply_text("⛔ Este comando solo funciona por chat privado.")
            return
        return await func(update, context, *args, **kwargs)

    return envoltura


def _solo_admin(func):
    async def envoltura(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if update.effective_user.id not in ADMINISTRADORES:
            await update.message.reply_text("⛔ Solo un administrador puede usar este comando.")
            return
        return await func(update, context, *args, **kwargs)

    return envoltura


async def chatid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Único comando abierto, sin autorización previa.
    En privado: muestra el ID de la persona.
    En un grupo: muestra el ID de la persona Y el del grupo."""
    usuario = update.effective_user
    chat = update.effective_chat
    if chat.type == "private":
        await update.message.reply_text(f"Tu ID de Telegram es: {usuario.id}")
    else:
        await update.message.reply_text(
            f"Tu ID de Telegram es: {usuario.id}\n"
            f"El ID de este grupo es: {chat.id}"
        )


@_solo_privado
@_solo_admin
async def autorizar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 3:
        await update.message.reply_text(
            "Uso: /autorizar <ID> <nombre> <rol>\nRoles válidos: comercial, logistica, admin"
        )
        return

    try:
        nuevo_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("El ID debe ser un número.")
        return

    rol = context.args[-1].lower()
    if rol not in ("comercial", "logistica", "admin"):
        await update.message.reply_text("Rol inválido. Usa: comercial, logistica o admin.")
        return

    nombre = " ".join(context.args[1:-1])
    if not nombre:
        await update.message.reply_text("Falta el nombre. Uso: /autorizar <ID> <nombre> <rol>")
        return

    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO usuarios (telegram_id, nombre, roles, autorizado_por)
            VALUES ($1, $2, ARRAY[$3]::TEXT[], $4)
            ON CONFLICT (telegram_id) DO UPDATE
            SET nombre = $2, roles = ARRAY[$3]::TEXT[], autorizado_por = $4
            """,
            nuevo_id, nombre, rol, update.effective_user.id,
        )
    await update.message.reply_text(
        f"✅ {nombre} (ID {nuevo_id}) autorizado como {rol}.\n"
        "(Si ya existía, esto reemplaza todos sus roles anteriores por este — "
        "usa /agregar_rol si quieres sumarle otro sin quitarle el actual.)"
    )


@_solo_privado
@_solo_admin
async def desautorizar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Uso: /desautorizar <ID>")
        return

    try:
        objetivo_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("El ID debe ser un número.")
        return

    if objetivo_id in USUARIOS_PERMITIDOS_FIJOS:
        await update.message.reply_text(
            "⛔ No se puede desautorizar a alguien de la lista fija del código. "
            "Eso requiere editar config.py directamente."
        )
        return

    pool = await get_pool()
    async with pool.acquire() as conn:
        resultado = await conn.execute("DELETE FROM usuarios WHERE telegram_id = $1", objetivo_id)

    if resultado.endswith("0"):
        await update.message.reply_text("Esa persona no estaba autorizada en la base de datos.")
    else:
        await update.message.reply_text(f"✅ Acceso revocado para el ID {objetivo_id}.")


@_solo_privado
@_solo_admin
async def agregar_rol(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Suma un rol adicional a alguien que ya está autorizado, sin quitarle los que ya tiene."""
    if len(context.args) < 2:
        await update.message.reply_text(
            "Uso: /agregar_rol <ID> <rol>\nRoles válidos: comercial, logistica, admin"
        )
        return

    try:
        objetivo_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("El ID debe ser un número.")
        return

    rol = context.args[1].lower()
    if rol not in ("comercial", "logistica", "admin"):
        await update.message.reply_text("Rol inválido. Usa: comercial, logistica o admin.")
        return

    if objetivo_id in USUARIOS_PERMITIDOS_FIJOS:
        await update.message.reply_text(
            "⛔ Esa persona está en la lista fija del código. Para cambiar sus roles, edita config.py."
        )
        return

    pool = await get_pool()
    async with pool.acquire() as conn:
        fila = await conn.fetchrow("SELECT nombre, roles FROM usuarios WHERE telegram_id = $1", objetivo_id)
        if fila is None:
            await update.message.reply_text(
                "Esa persona no está autorizada todavía. Usa /autorizar primero para darla de alta."
            )
            return
        if rol in fila["roles"]:
            await update.message.reply_text(f"{fila['nombre']} ya tiene el rol {rol}.")
            return
        await conn.execute(
            "UPDATE usuarios SET roles = array_append(roles, $1) WHERE telegram_id = $2",
            rol, objetivo_id,
        )
    await update.message.reply_text(f"✅ {fila['nombre']} ahora también tiene el rol {rol}.")


@_solo_privado
@_solo_admin
async def quitar_rol(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Quita un rol puntual sin desautorizar a la persona por completo."""
    if len(context.args) < 2:
        await update.message.reply_text("Uso: /quitar_rol <ID> <rol>")
        return

    try:
        objetivo_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("El ID debe ser un número.")
        return

    rol = context.args[1].lower()

    if objetivo_id in USUARIOS_PERMITIDOS_FIJOS:
        await update.message.reply_text(
            "⛔ Esa persona está en la lista fija del código. Para cambiar sus roles, edita config.py."
        )
        return

    pool = await get_pool()
    async with pool.acquire() as conn:
        fila = await conn.fetchrow("SELECT nombre, roles FROM usuarios WHERE telegram_id = $1", objetivo_id)
        if fila is None:
            await update.message.reply_text("Esa persona no está autorizada.")
            return
        if rol not in fila["roles"]:
            await update.message.reply_text(f"{fila['nombre']} no tiene el rol {rol}.")
            return

        nuevos_roles = [r for r in fila["roles"] if r != rol]
        if not nuevos_roles:
            await update.message.reply_text(
                "Ese es su único rol — si quieres quitarle todo el acceso usa /desautorizar en su lugar."
            )
            return

        await conn.execute("UPDATE usuarios SET roles = $1 WHERE telegram_id = $2", nuevos_roles, objetivo_id)
    await update.message.reply_text(f"✅ Se quitó el rol {rol} a {fila['nombre']}.")


@_solo_privado
@_solo_admin
async def usuarios(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lineas = ["*Usuarios autorizados*", "", "_Lista fija (código):_"]
    for tid, (nombre, roles) in USUARIOS_PERMITIDOS_FIJOS.items():
        lineas.append(f"• {nombre} — {', '.join(roles)} — `{tid}`")
    if not USUARIOS_PERMITIDOS_FIJOS:
        lineas.append("(ninguno)")

    pool = await get_pool()
    async with pool.acquire() as conn:
        filas = await conn.fetch("SELECT telegram_id, nombre, roles FROM usuarios ORDER BY nombre")

    lineas.append("")
    lineas.append("_Base de datos:_")
    if not filas:
        lineas.append("(ninguno)")
    for fila in filas:
        lineas.append(f"• {fila['nombre']} — {', '.join(fila['roles'])} — `{fila['telegram_id']}`")

    await update.message.reply_text("\n".join(lineas), parse_mode="Markdown")


@_solo_privado
@_solo_admin
async def auditoria(update: Update, context: ContextTypes.DEFAULT_TYPE):
    solo_bloqueados = bool(context.args) and context.args[0].lower() == "bloqueados"

    pool = await get_pool()
    async with pool.acquire() as conn:
        if solo_bloqueados:
            filas = await conn.fetch(
                "SELECT * FROM auditoria WHERE resultado = 'bloqueado' ORDER BY fecha DESC LIMIT 30"
            )
        else:
            filas = await conn.fetch("SELECT * FROM auditoria ORDER BY fecha DESC LIMIT 30")

    if not filas:
        await update.message.reply_text("No hay registros de auditoría todavía.")
        return

    lineas = []
    for fila in filas:
        marca = "✅" if fila["resultado"] == "autorizado" else "⛔"
        lineas.append(
            f"{marca} {fila['fecha']:%Y-%m-%d %H:%M} — {fila['nombre']} — "
            f"{fila['comando']} — {fila['chat_nombre'] or 'privado'}"
        )
    await update.message.reply_text("\n".join(lineas))


_CAMPOS_AJUSTABLES = ("en_almacen", "pendiente_por_llegar", "reservado")


@_solo_privado
@_solo_admin
async def ajustar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/ajustar <marca> <modelo> <potencia> <campo> <nuevo_valor> <motivo...> — exclusivo admin."""
    if len(context.args) < 5:
        await update.message.reply_text(
            "Uso: /ajustar <marca> <modelo> <potencia> <campo> <nuevo_valor> <motivo>\n"
            f"Campos válidos: {', '.join(_CAMPOS_AJUSTABLES)}"
        )
        return

    marca, modelo, potencia_txt, campo, valor_txt, *motivo_partes = context.args
    campo = campo.lower()
    if campo not in _CAMPOS_AJUSTABLES:
        await update.message.reply_text(f"Campo inválido. Usa: {', '.join(_CAMPOS_AJUSTABLES)}")
        return

    try:
        potencia = int(potencia_txt)
        nuevo_valor = int(valor_txt)
    except ValueError:
        await update.message.reply_text("La potencia y el nuevo valor deben ser números enteros.")
        return

    motivo = " ".join(motivo_partes) or "(sin motivo especificado)"

    pool = await get_pool()
    async with pool.acquire() as conn:
        fila_actual = await conn.fetchrow(
            f"SELECT {campo} FROM paneles_stock WHERE marca=$1 AND modelo=$2 AND potencia_w=$3",
            marca, modelo, potencia,
        )
        if fila_actual is None:
            await update.message.reply_text(
                "No existe ese registro de marca/modelo/potencia en paneles_stock."
            )
            return
        valor_anterior = fila_actual[campo]

        await conn.execute(
            f"UPDATE paneles_stock SET {campo} = $1 WHERE marca=$2 AND modelo=$3 AND potencia_w=$4",
            nuevo_valor, marca, modelo, potencia,
        )

    await registrar_intento(
        update.effective_user.id, update.effective_user.full_name, "/ajustar",
        update.effective_chat.id, update.effective_chat.title, "autorizado",
        detalle=f"{marca} {modelo} {potencia}W: {campo} {valor_anterior} → {nuevo_valor}. Motivo: {motivo}",
    )

    await update.message.reply_text(
        f"✅ {marca} {modelo} {potencia}W — {campo}: {valor_anterior} → {nuevo_valor}\nMotivo: {motivo}"
    )
