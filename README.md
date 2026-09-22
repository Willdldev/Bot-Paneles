# Bot de inventario de paneles — Escala Solar

# Bot de inventario de paneles — Escala Solar

## Qué incluye esta versión (los 4 grupos completos)

- Base de datos completa (`schema.sql`).
- Seguridad completa: guardián global, autorización por rol (comercial /
  logística / admin — **una persona puede tener más de un rol**), doble
  fuente de autorización, auditoría de cada intento. Cada comando de
  negocio está restringido a su rol: `/reservar` solo comercial/admin;
  `/entrada`, `/orden_pendiente`, `/salida` solo logística/admin.
- Comandos administrativos: `/chatid`, `/autorizar`, `/desautorizar`,
  `/agregar_rol`, `/quitar_rol`, `/usuarios`, `/auditoria`, `/ajustar`.
- **Inventario paneles**: `/inventario` (vista física), `/disponible`
  (vista comercial, incluye pendiente por llegar) y `/movimientos`
  (historial de entradas y salidas de almacén) — todos con resumen
  corto + botón de Excel con el detalle completo.
- **Reservar Paneles**: `/reservar` (paso a paso, valida disponible dos
  veces para evitar condiciones de carrera), `/pendientes` (sin
  confirmar en Odoo), `/reservas` (todas las activas), botón "Ya lo
  registré en Odoo" exclusivo de logística.
- **Entrada paneles almacén**: `/entrada` (fecha, marca, modelo,
  potencia, cantidad, proveedor, orden, y valida cada asignación a
  proyecto contra las reservas reales), `/orden_pendiente` (registra
  una compra que aún no llega), `/ordenes_pendientes`.
- **Salidas paneles de almacén**: `/salida` — puede o no venir de una
  reserva, pide tipo (almacén / entrega directa) y origen (local /
  internacional / desconocido), recibe fotos de las series y las lee
  con OCR (Tesseract, gratis y local), valida que no se repitan (ni en
  el lote actual ni en el historial completo), exige que la cantidad
  de series coincida exactamente con lo declarado, y al confirmar
  descuenta el inventario correcto y guarda las series para garantía.
  Si la lectura automática falla, se puede escribir la serie a mano.

- **Paneles dañados** (Almacén y Reservar Paneles, cualquier rol):
  `/reportar_dano` — marca, modelo, potencia, cantidad, si está ligado a
  una reserva (Sí/No, y si sí el número) y el motivo. Resta de
  `en_almacen` y suma a `danados`; si estaba ligado a una reserva,
  también le resta esa cantidad a `reservado` y a la reserva misma, para
  que `/salida` nunca intente despachar más de lo que en realidad queda
  sano. `/reportes_dano` muestra el historial.

## 1. Base de datos (Supabase, gratis)

1. Crea una cuenta en [supabase.com](https://supabase.com) y un proyecto nuevo.
2. En el proyecto, ve a *Project Settings → Database → Connection string*
   y copia la cadena en modo "URI".
3. Pégala como `DATABASE_URL`. El bot crea las tablas solo la primera
   vez que arranca.

## 2. El bot de Telegram

1. Habla con **@BotFather** en Telegram, `/newbot`, sigue los pasos y
   copia el token que te da.
2. Agrega el bot a tus 4 grupos (Reservar Paneles, Entrada paneles
   almacén, Inventario paneles, Salidas paneles de almacén).
3. Dale al bot **permiso de administrador** en cada grupo, o al menos
   desactiva la privacidad con `/setprivacy` → *Disable* en @BotFather,
   para que pueda leer todos los mensajes del grupo (necesario para las
   fotos de series en Salidas).

## 3. Obtener los IDs de grupo y tu propio ID

1. Antes de tener ningún usuario autorizado, edita `config.py` y
   agrega tu propio ID de Telegram a `USUARIOS_PERMITIDOS_FIJOS` y a
   `ADMINISTRADORES`. Si no sabes tu ID, escríbele por privado a
   **@userinfobot**.
2. Con el bot corriendo, entra a cada uno de los 4 grupos y escribe
   `/chatid` — es el único comando que funciona sin autorización.
3. Copia esos 4 IDs en `COMERCIAL_GROUP_ID`, `ALMACEN_GROUP_ID`,
   `VALIDACION_GROUP_ID`, `SALIDA_GROUP_ID`.

## 4. Desplegar en Railway (gratis, con límites)

1. Sube esta carpeta a un repositorio de GitHub (incluye `nixpacks.toml`
   tal cual está — es lo que le dice a Railway que instale el binario
   de Tesseract, ya que `pytesseract` por sí solo no lo trae).
2. En [railway.app](https://railway.app), *New Project → Deploy from
   GitHub repo*, elige el repo.
3. En *Variables*, agrega `BOT_TOKEN`, `DATABASE_URL` y los 4 IDs de
   grupo.
4. *Settings → Deploy → Start Command*:
   ```
   python bot.py
   ```
5. Despliega. En los *Logs* deberías ver "Bot iniciado, esperando
   mensajes...".

## 5. Dar de alta al resto del equipo

Por privado con el bot (tú, como admin):
```
/autorizar 987654321 Juan Pérez comercial
/autorizar 123123123 María Ruiz logistica
```
Si alguien necesita hacer ambas funciones, o cambia de área:
```
/agregar_rol 987654321 logistica   -> ahora tiene comercial y logistica
/quitar_rol 987654321 comercial    -> le queda solo logistica
```
`/autorizar` sobre alguien que ya existe reemplaza todos sus roles por
el que le pongas — para sumar uno sin perder el actual, usa `/agregar_rol`.

## Notas de diseño a tener presentes

- No se maneja por lote: todo se agrega por **marca + modelo +
  potencia**. `disponible` nunca se guarda directo, siempre se
  calcula (distinto según la vista física o comercial).
- El número de orden de compra es solo dato contable — el "cuadre"
  real entre lo que llega y lo que comercial reservó se hace por
  **proyecto**, no por orden (paneles de la misma marca/modelo/potencia
  son intercambiables entre sí).
- Al despachar con reserva: se descuenta `en_almacen` y `reservado`
  juntos (el disponible total no cambia, porque la reserva ya lo había
  descontado). Sin reserva: solo se descuenta `en_almacen`, validado
  contra lo que de verdad está libre (no reservado por alguien más).
- `/ajustar` es exclusivo de administradores y deja registro completo
  en `auditoria`.
- Cuando subas el documento inicial de inventario, se puede construir
  un script aparte que llene `paneles_stock`, `ordenes_compra` y
  `reservas` de una sola vez, en vez de arrancar la base vacía.

