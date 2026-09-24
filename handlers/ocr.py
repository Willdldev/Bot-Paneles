"""
Lee el número de serie de la foto de una etiqueta de panel.

Primero intenta decodificar el código de barras directamente (pyzbar) —
si la librería del sistema está disponible, es lo más confiable. Como
respaldo, usa EasyOCR — un lector de texto 100% Python/pip (basado en
PyTorch), que no depende de instalar ningún binario en el sistema como
pasaba con Tesseract (eso fue justo la fuente de varios problemas de
despliegue en Railway).

EasyOCR es más lento que Tesseract, así que la imagen se reduce antes
de procesarla (1200px de lado mayor da un buen balance entre velocidad
y precisión, confirmado con fotos reales) y la inferencia corre en un
hilo aparte para no congelar el bot mientras procesa.
"""
import asyncio
import ctypes
import ctypes.util
import io
import logging
import re
import threading

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

_PATRON_SERIAL = re.compile(r"[A-Z0-9]{8,}")
_LADO_MAYOR_MAXIMO = 1200


def _cargar_libzbar():
    """
    pyzbar solo sabe pedirle la librería a ctypes.util.find_library(),
    que en varios entornos de contenedores no encuentra bibliotecas
    recién instaladas. Probamos rutas conocidas de Linux como respaldo.
    """
    candidatos = [
        ctypes.util.find_library("zbar"),
        "libzbar.so.0",
        "/usr/lib/x86_64-linux-gnu/libzbar.so.0",
        "/usr/lib/aarch64-linux-gnu/libzbar.so.0",
        "/lib/x86_64-linux-gnu/libzbar.so.0",
        "/usr/lib/libzbar.so.0",
        "/usr/local/lib/libzbar.so.0",
    ]
    ultimo_error = None
    for candidato in candidatos:
        if not candidato:
            continue
        try:
            return ctypes.cdll.LoadLibrary(candidato)
        except OSError as error:
            ultimo_error = error
            continue
    raise ImportError(f"No se pudo cargar libzbar desde ninguna ruta conocida: {ultimo_error}")


try:
    import pyzbar.zbar_library as _zbar_library

    _zbar_library.load = lambda: (_cargar_libzbar(), [])
    from pyzbar.pyzbar import decode as decodificar_barras
    _ZBAR_DISPONIBLE = True
except Exception:
    logger.warning(
        "No se pudo cargar la librería zbar — la lectura de series seguirá "
        "funcionando solo con EasyOCR (algo más lenta, pero no depende de "
        "ningún binario del sistema)."
    )
    decodificar_barras = None
    _ZBAR_DISPONIBLE = False


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
    cargado antes de que llegue la primera foto (si no, la primera
    persona que use /salida tendría que esperar la descarga)."""
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


def _leer_con_easyocr_sync(imagen: Image.Image) -> list[str]:
    lector = _obtener_lector()
    imagen_reducida = _reducir_imagen(imagen.convert("RGB"))
    return lector.readtext(np.array(imagen_reducida), detail=0)


async def extraer_serie(imagen_bytes: bytes) -> str | None:
    """Devuelve el número de serie en mayúsculas, o None si no se pudo
    leer con confianza (ni por código de barras ni por texto)."""
    try:
        imagen = Image.open(io.BytesIO(imagen_bytes))

        # 1) Código de barras primero — mucho más confiable y más rápido.
        if _ZBAR_DISPONIBLE:
            codigos = decodificar_barras(imagen)
            if codigos:
                valor = codigos[0].data.decode("utf-8", errors="ignore").strip().upper()
                if valor:
                    return valor

        # 2) Respaldo: leer el texto impreso con EasyOCR, en un hilo
        # aparte para no congelar el bot mientras procesa.
        fragmentos = await asyncio.to_thread(_leer_con_easyocr_sync, imagen)
        return _mejor_candidato(fragmentos)
    except Exception:
        logger.exception("Fallo leyendo la serie del panel.")
        return None
