-- Esquema del bot de inventario de paneles (Escala Solar)
-- Se ejecuta automáticamente al iniciar el bot (ver db.py). Es seguro
-- correrlo varias veces: todo usa IF NOT EXISTS.

CREATE TABLE IF NOT EXISTS usuarios (
    telegram_id BIGINT PRIMARY KEY,
    nombre TEXT NOT NULL,
    -- una persona puede tener más de un rol a la vez (ej. comercial y logística)
    roles TEXT[] NOT NULL DEFAULT '{}'::TEXT[],
    autorizado_por BIGINT,
    fecha_autorizacion TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (roles <@ ARRAY['comercial', 'logistica', 'admin']::TEXT[])
);

-- Totales agregados por marca+modelo+potencia. No se maneja por lote:
-- "disponible" siempre se calcula, nunca se guarda directamente.
CREATE TABLE IF NOT EXISTS paneles_stock (
    id SERIAL PRIMARY KEY,
    marca TEXT NOT NULL,
    modelo TEXT NOT NULL,
    potencia_w INTEGER NOT NULL,
    en_almacen INTEGER NOT NULL DEFAULT 0,
    pendiente_por_llegar INTEGER NOT NULL DEFAULT 0,
    reservado INTEGER NOT NULL DEFAULT 0,
    -- paneles físicamente en almacén pero dañados: no cuentan como
    -- disponibles ni como en_almacen "sano". Se restan de en_almacen
    -- al reportarlos (ver /reportar_dano).
    danados INTEGER NOT NULL DEFAULT 0,
    UNIQUE (marca, modelo, potencia_w),
    CHECK (en_almacen >= 0),
    CHECK (pendiente_por_llegar >= 0),
    CHECK (reservado >= 0),
    CHECK (danados >= 0)
);

CREATE TABLE IF NOT EXISTS ordenes_compra (
    id SERIAL PRIMARY KEY,
    proveedor TEXT NOT NULL,
    marca TEXT NOT NULL,
    modelo TEXT NOT NULL,
    potencia_w INTEGER NOT NULL,
    cantidad INTEGER NOT NULL,
    numero_orden TEXT,
    -- 'almacen': entra físicamente a la bodega. 'directa': va directo al
    -- proyecto sin pasar por almacén (nunca incrementa en_almacen).
    -- NULL mientras la orden sigue pendiente (aún no se sabe cómo se resolverá).
    tipo_entrega TEXT CHECK (tipo_entrega IN ('almacen', 'directa')),
    estado TEXT NOT NULL DEFAULT 'pendiente' CHECK (estado IN ('pendiente', 'recibida')),
    proyecto TEXT,
    registrado_por BIGINT REFERENCES usuarios(telegram_id),
    fecha_registro TIMESTAMPTZ NOT NULL DEFAULT now(),
    fecha_recepcion TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS reservas (
    id SERIAL PRIMARY KEY,
    marca TEXT NOT NULL,
    modelo TEXT NOT NULL,
    potencia_w INTEGER NOT NULL,
    cantidad INTEGER NOT NULL,
    proyecto TEXT NOT NULL,
    solicitado_por BIGINT REFERENCES usuarios(telegram_id),
    fecha_solicitud TIMESTAMPTZ NOT NULL DEFAULT now(),
    estado_odoo TEXT NOT NULL DEFAULT 'pendiente' CHECK (estado_odoo IN ('pendiente', 'confirmada')),
    confirmado_por BIGINT REFERENCES usuarios(telegram_id),
    fecha_confirmacion_odoo TIMESTAMPTZ,
    estado_despacho TEXT NOT NULL DEFAULT 'pendiente' CHECK (estado_despacho IN ('pendiente', 'parcial', 'despachada')),
    -- para poder editar el mensaje del botón "Ya lo registré en Odoo" una vez confirmado
    mensaje_odoo_chat_id BIGINT,
    mensaje_odoo_message_id BIGINT
);

CREATE TABLE IF NOT EXISTS despachos (
    id SERIAL PRIMARY KEY,
    reserva_id INTEGER REFERENCES reservas(id),
    tipo TEXT NOT NULL DEFAULT 'almacen' CHECK (tipo IN ('almacen', 'directa')),
    destino TEXT NOT NULL,
    marca TEXT NOT NULL,
    modelo TEXT NOT NULL,
    potencia_w INTEGER NOT NULL,
    cantidad_declarada INTEGER NOT NULL,
    origen_compra TEXT NOT NULL CHECK (origen_compra IN ('local', 'internacional', 'desconocido')),
    registrado_por BIGINT REFERENCES usuarios(telegram_id),
    fecha TIMESTAMPTZ NOT NULL DEFAULT now(),
    confirmado BOOLEAN NOT NULL DEFAULT false
);

-- Historial completo de series despachadas. La validación de duplicados
-- en Salidas consulta esta tabla (serial es único a nivel de todo el negocio).
CREATE TABLE IF NOT EXISTS series_panel (
    serial TEXT PRIMARY KEY,
    despacho_id INTEGER REFERENCES despachos(id),
    marca TEXT NOT NULL,
    modelo TEXT NOT NULL,
    potencia_w INTEGER NOT NULL,
    fecha_registro TIMESTAMPTZ NOT NULL DEFAULT now(),
    foto_file_id TEXT
);

-- Historial de paneles reportados como dañados (rotos, defectuosos, etc.)
CREATE TABLE IF NOT EXISTS reportes_dano (
    id SERIAL PRIMARY KEY,
    marca TEXT NOT NULL,
    modelo TEXT NOT NULL,
    potencia_w INTEGER NOT NULL,
    cantidad INTEGER NOT NULL,
    reserva_id INTEGER REFERENCES reservas(id),
    motivo TEXT NOT NULL,
    reportado_por BIGINT REFERENCES usuarios(telegram_id),
    fecha TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS auditoria (
    id SERIAL PRIMARY KEY,
    telegram_id BIGINT,
    nombre TEXT,
    comando TEXT,
    chat_id BIGINT,
    chat_nombre TEXT,
    resultado TEXT NOT NULL CHECK (resultado IN ('autorizado', 'bloqueado')),
    detalle TEXT,
    fecha TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_auditoria_fecha ON auditoria (fecha DESC);
CREATE INDEX IF NOT EXISTS idx_stock_marca_modelo_potencia ON paneles_stock (marca, modelo, potencia_w);
