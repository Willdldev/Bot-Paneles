"""
Carga inicial del inventario real — correr UNA sola vez, después de que
el bot haya arrancado al menos una vez (para que existan las tablas).

Uso:
    DATABASE_URL="postgresql://..." python seed_inicial.py

Datos tomados de Inventario_paneles_y_reservados.xlsx. Decisiones
confirmadas con el equipo al construir esta carga:

- Los 65 paneles JA Solar 425W reservados (PANELES GRUPO RAMOS 45 +
  Taller Luis Tito 20) se asignaron a la variante de catálogo "N"
  (84 en almacén), no a la "G" (7 en almacén) — el archivo original no
  distinguía cuál de las dos.
- No se crean órdenes de compra (tabla ordenes_compra) para esta carga:
  ninguno de estos registros tenía una orden real asociada en el
  archivo — se decidió no inventar una.
- Los 934 paneles GCL 455W "reservado, no en almacén" se cargan con
  pendiente_por_llegar = 934 (igual a lo reservado), para que el
  disponible cuadre en 0 en vez de salir negativo, sin necesidad de una
  orden de compra real detrás.
- Las reservas importadas quedan con estado_odoo = 'confirmada' (ya
  existían en el negocio antes del bot) y estado_despacho = 'pendiente'
  (todavía no se han despachado a través del bot).
- El código "SFAU" de la columna original no se usó — se consideró
  irrelevante para el sistema.
"""
import asyncio
import os
import sys

import asyncpg

DATABASE_URL = os.environ["DATABASE_URL"]

# (marca, modelo, potencia_w, en_almacen, pendiente_por_llegar, reservado)
PANELES_STOCK = [
    ("Atersa", "A-250P", 250, 1, 0, 0),
    ("Atersa", "A-260P", 260, 1, 0, 0),
    ("Canadian Solar", "CS6K-270P", 270, 2, 0, 0),
    ("Canadian Solar", "CS3K-320MS", 320, 1, 0, 0),
    ("JA Solar", "JAP72S01-325SC", 325, 2, 0, 0),
    ("SunPower", "SPR-E20-327-COM", 327, 11, 0, 1),
    ("SunPower", "SPR-333NE-WHT-D", 333, 8, 0, 0),
    ("JA Solar", "JAM60D10-340MB", 340, 12, 0, 12),
    ("JA Solar", "JAM60S10-345MR", 345, 17, 0, 14),
    ("JA Solar", "JAM60S20-385MR N", 385, 6, 0, 6),
    ("Canadian Solar", "CS1U-410MS", 410, 1, 0, 0),
    ("JA Solar", "JAM54S30-415GR", 415, 41, 0, 0),
    ("Longi", "LR5-54HPH-415M", 415, 4, 0, 0),
    ("JA Solar", "JAM54S30-425LR G", 425, 7, 0, 0),
    ("JA Solar", "JAM54S30-425LR N", 425, 84, 0, 65),
    ("Longi", "LR5-54HTH-435M", 435, 25, 0, 10),
    ("JA Solar", "JAM54D40-450LB", 450, 327, 0, 326),
    ("Jinko Solar", "JKM450M-60HL4-V", 450, 12, 0, 0),
    ("JA Solar", "JAM72S20-460MR", 460, 43, 0, 43),
    ("Jinko Solar", "JKM465N-60HL4-V", 465, 31, 0, 0),
    ("JA Solar", "JAM66S30-500MR", 500, 13, 0, 0),
    ("Atersa", "A-550M-GS", 550, 2, 0, 0),
    ("JA Solar", "JAM72D40-595MB", 595, 38, 0, 32),
    ("JA Solar", "JAM72D40-600LB", 600, 6, 0, 0),
    ("JA Solar", "JAM66D45LB", 620, 20, 0, 20),
    ("GCL", "TOPCON NT12R/66GDF", 630, 146, 0, 136),
    ("GCL", "NT12R/48GDF-J2", 455, 0, 934, 934),  # sin almacén, ver nota arriba
]

# (marca, modelo, potencia_w, cantidad, proyecto)
RESERVAS = [
    ("SunPower", "SPR-E20-327-COM", 327, 1, "Empresas vibra"),
    ("JA Solar", "JAM60D10-340MB", 340, 12, "STOCK SIRENA PUERTO PLATA"),
    ("JA Solar", "JAM60S10-345MR", 345, 14, "STOCK SIRENA EMBRUJO Y SADHALA"),
    ("JA Solar", "JAM60S20-385MR N", 385, 6, "SUPER POLA TERRENAS STOCK"),
    ("JA Solar", "JAM54S30-425LR N", 425, 45, "PANELES GRUPO RAMOS"),
    ("JA Solar", "JAM54S30-425LR N", 425, 20, "Taller Luis Tito"),
    ("JA Solar", "JAM54D40-450LB", 450, 236, "PANELES GRUPO RAMOS"),
    ("JA Solar", "JAM54D40-450LB", 450, 54, "Cesar Armenteros Iglesias"),
    ("JA Solar", "JAM54D40-450LB", 450, 36, "Cesar Armenteros Iglesias"),
    ("GCL", "NT12R/48GDF-J2", 455, 29, "DAMARIS REINOSO"),
    ("GCL", "NT12R/48GDF-J2", 455, 29, "JULIO DE LOS SANTOS"),
    ("JA Solar", "JAM72S20-460MR", 460, 1, "SIRENA BANI STOCK"),
    ("JA Solar", "JAM72S20-460MR", 460, 2, "SIRENA LAS CAOBAS STOCK"),
    ("GCL", "NT12R/48GDF-J2", 455, 22, "JANELLE LUCIANO"),
    ("GCL", "NT12R/48GDF-J2", 455, 396, "ISOTEX FASE II"),
    ("GCL", "NT12R/48GDF-J2", 455, 14, "ISOTEX FASE III"),
    ("JA Solar", "JAM72S20-460MR", 460, 18, "STEFANO PIEROTTI"),
    ("JA Solar", "JAM72S20-460MR", 460, 22, "PANELES GRUPO RAMOS"),
    ("JA Solar", "JAM72D40-595MB", 595, 10, "CAUCEDO FASE IV"),
    ("GCL", "NT12R/48GDF-J2", 455, 400, "PREFABRICADOS ALPHA"),
    ("JA Solar", "JAM72D40-595MB", 595, 22, "CAPUTO RACING PERFORMANCE"),
    ("GCL", "NT12R/48GDF-J2", 455, 22, "Dulces y Pasteles Varsovia Ramirez"),
    ("GCL", "NT12R/48GDF-J2", 455, 22, "Alice Dahiana Perez Ventura (Sto. Dgo.)"),
    ("JA Solar", "JAM66D45LB", 620, 20, "Miguelina Portela"),
    ("GCL", "TOPCON NT12R/66GDF", 630, 72, "MELYZA RIVERA AVILES"),
    ("GCL", "TOPCON NT12R/66GDF", 630, 64, "EL CATADOR MONUMENTAL"),
    ("Longi", "LR5-54HTH-435M", 435, 10, "AMPL. PALLADIUM BAVARO"),
]


async def main():
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        existentes = await conn.fetchval("SELECT COUNT(*) FROM reservas")
        if existentes and "--forzar" not in sys.argv:
            print(
                f"Ya hay {existentes} reserva(s) en la base de datos. Este script es para la carga "
                "inicial, una sola vez — correrlo de nuevo duplicaría reservas. Si de verdad quieres "
                "forzarlo, corre: python seed_inicial.py --forzar"
            )
            return

        print(f"Cargando {len(PANELES_STOCK)} SKUs en paneles_stock...")
        for marca, modelo, potencia, en_almacen, pendiente, reservado in PANELES_STOCK:
            await conn.execute(
                """
                INSERT INTO paneles_stock (marca, modelo, potencia_w, en_almacen, pendiente_por_llegar, reservado)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (marca, modelo, potencia_w) DO UPDATE
                SET en_almacen = $4, pendiente_por_llegar = $5, reservado = $6
                """,
                marca, modelo, potencia, en_almacen, pendiente, reservado,
            )

        print(f"Cargando {len(RESERVAS)} reservas...")
        for marca, modelo, potencia, cantidad, proyecto in RESERVAS:
            await conn.execute(
                """
                INSERT INTO reservas (marca, modelo, potencia_w, cantidad, proyecto, estado_odoo, estado_despacho)
                VALUES ($1, $2, $3, $4, $5, 'confirmada', 'pendiente')
                """,
                marca, modelo, potencia, cantidad, proyecto,
            )

        print("Listo. Verifica con /inventario y /disponible en el bot.")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
