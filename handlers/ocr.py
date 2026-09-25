"""
Lee el número de serie de la foto de una etiqueta de panel.

Primero intenta decodificar el código de barras con zxing-cpp — una
librería de lectura de códigos que viene compilada dentro del propio
paquete de Python, sin depender de instalar nada en el sistema (a
diferencia de pyzbar/libzbar, que nunca logramos hacer funcionar en
Railway). Se prueba la foto completa y unos pocos recortes centrados,
ya que el código de barras se lee casi al instante (una fracción de
segundo) cuando ocupa una porción razonable del recorte — y probar
varios recortes sigue siendo mucho más rápido que EasyOCR.

Solo si ningún recorte trae un código de barras se usa EasyOCR (lector
de texto en Python puro, más lento pero más tolerante quando el código
no se ve bien o la foto es de mala calidad) como respaldo.
"""
import asyncio
import io
import logging
import re
import threading

import numpy as np
import zxingcpp
from PIL import Image

logger = logging.getLogger(__name__)

_PATRON_SERIAL = re.compile(r"[A-Z0-9]{8,}")
_LADO_MAYOR_MAXIMO = 1200


def _recortes_a_probar(imagen: Image.Image):
    """La imagen completa primero, luego unos pocos recortes centrados
    cada vez más cerrados — cada intento cuesta una fracción de
    segundo, y entre todos cubren la mayoría de fotos donde la
    etiqueta no llena todo el cuadro."""
    ancho, alto = imagen.size
    yield imagen
    for fraccion in (0.7, 0.5, 0.35):
        mx, my = int(ancho * (1 - fraccion) / 2), int(alto * (1 - fraccion) / 2)
        yield imagen.crop((mx, my, ancho - mx, alto - my))
    yield imagen.crop((0, 0, ancho, alto // 2))
    yield imagen.crop((0, alto // 2, ancho, alto))


def _leer_codigo_de_barras(imagen: Image.Image) -> str | None:
    for recorte in _recortes_a_probar(imagen):
        resultados = zxingcpp.read_barcodes(recorte)
        if resultados:
            valor = resultados[0].text.strip().upper()
            if valor:
                return valor
    return None


_lector_ocr = None
_candado_lector = threading.Lock()


def _obtener_lector():
    """Crea el lector de EasyOCR una sola vez (carga los modelos — tarda,
    la primera vez que se llama, mientras se descargan)."""
    global _lector_ocr
    with _candado_lector:
        if _lector_ocr is None:
            import easyocr
            logger.info("Cargando el modelo de EasyOCR (puede tardar la primera vez)...")
            _lector_ocr = easyocr.Reader(["en"], gpu=False, verbose=False)
            logger.info("Modelo de EasyOCR listo.")
    return _lector_ocr


async def precargar_lector():
    """Se llama una vez al arrancar el bot, para que el modelo ya esté
    cargado antes de que llegue la primera foto."""
    await asyncio.to_thread(_obtener_lector)


def _reducir_imagen(imagen: Image.Image) -> Image.Image:
    ancho, alto = imagen.size
    lado_mayor = max(ancho, alto)
    if lado_mayor <= _LADO_MAYOR_MAXIMO:
        return imagen
    factor = _LADO_MAYOR_MAXIMO / lado_mayor
    return imagen.resize((int(ancho * factor), int(alto * factor)), Image.LANCZOS)


def _mejor_candidato(fragmentos: list[str]) -> str | None:
    texto_completo = " ".join(fragmentos)
    candidatos = _PATRON_SERIAL.findall(texto_completo.upper())
    if not candidatos:
        return None
    return max(candidatos, key=len)


def _leer_con_easyocr(imagen: Image.Image) -> list[str]:
    lector = _obtener_lector()
    imagen_reducida = _reducir_imagen(imagen)
    return lector.readtext(np.array(imagen_reducida), detail=0)


def _leer_serie_sync(imagen: Image.Image) -> str | None:
    """Corre en un hilo aparte para no congelar el bot. Primero código
    de barras (rápido); si no aparece ninguno, EasyOCR (lento)."""
    valor = _leer_codigo_de_barras(imagen)
    if valor:
        return valor
    fragmentos = _leer_con_easyocr(imagen)
    return _mejor_candidato(fragmentos)


def _todos_los_codigos_sync(imagen: Image.Image) -> list[str]:
    """A diferencia de _leer_codigo_de_barras (que se detiene en el primer
    código que encuentra), esta recorre TODOS los códigos de barras visibles
    en la imagen — pensada para una foto de una hoja/packing list con varios
    paneles a la vez, no para la foto de un solo panel."""
    try:
        resultados = zxingcpp.read_barcodes(imagen)
    except Exception:
        return []
    vistos = set()
    codigos = []
    for r in resultados:
        valor = r.text.strip().upper()
        if valor and valor not in vistos:
            vistos.add(valor)
            codigos.append(valor)
    return codigos


async def extraer_codigos_de_barras(imagen_bytes: bytes) -> list[str]:
    """Devuelve la lista de todos los códigos de barras distintos encontrados
    en la foto (puede ser vacía, uno, o varios si es una hoja con muchos)."""
    try:
        imagen = Image.open(io.BytesIO(imagen_bytes)).convert("RGB")
        return await asyncio.to_thread(_todos_los_codigos_sync, imagen)
    except Exception:
        logger.exception("Fallo leyendo códigos de barras múltiples.")
        return []


async def extraer_serie(imagen_bytes: bytes) -> str | None:
    """Devuelve el número de serie en mayúsculas, o None si no se pudo
    leer con confianza (ni por código de barras ni por texto)."""
    try:
        imagen = Image.open(io.BytesIO(imagen_bytes)).convert("RGB")
        return await asyncio.to_thread(_leer_serie_sync, imagen)
    except Exception:
        logger.exception("Fallo leyendo la serie del panel.")
        return None
