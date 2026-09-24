"""
Lee el número de serie de la foto de una etiqueta de panel.

Primero intenta decodificar el código de barras directamente (pyzbar,
sobre la librería ZBar) — es mucho más confiable que leer el texto
impreso, porque no depende de reconocer letras/números, solo de
detectar el patrón de barras. Funciona incluso con bastante ruido
alrededor (fondo, otros objetos, poca luz).

Si la etiqueta no tiene código de barras legible (dañado, foto muy
mala, ángulo imposible), cae de respaldo a leer el texto impreso con
Tesseract — más débil, pero mejor que nada.
"""
import ctypes
import ctypes.util
import io
import logging
import re

import pytesseract
from PIL import Image, ImageOps, ImageFilter

logger = logging.getLogger(__name__)


def _cargar_libzbar():
    """
    pyzbar solo sabe pedirle la librería a ctypes.util.find_library(),
    que en varios entornos de contenedores (Railway incluido) no
    encuentra bibliotecas recién instaladas por apt porque depende de
    un índice (ldconfig) que no se actualiza ahí. Probamos rutas
    conocidas de Linux directamente como respaldo, en vez de confiar
    solo en esa búsqueda automática.
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
    logger.exception(
        "No se pudo cargar la librería zbar — la lectura de series seguirá "
        "funcionando solo con Tesseract (menos confiable)."
    )
    decodificar_barras = None
    _ZBAR_DISPONIBLE = False

# Un número de serie de panel suele ser una cadena alfanumérica larga,
# sin espacios. Ajusta este patrón si tus paneles usan otro formato.
_PATRON_SERIAL = re.compile(r"[A-Z0-9]{8,}")


def _preprocesar(imagen: Image.Image) -> Image.Image:
    """Escala de grises, agranda, aumenta contraste y binariza — mejora
    bastante lo que Tesseract puede leer en una foto de celular."""
    imagen = imagen.convert("L")
    ancho, alto = imagen.size
    lado_mayor = max(ancho, alto)
    if lado_mayor < 1600:
        factor = 1600 / lado_mayor
        imagen = imagen.resize((int(ancho * factor), int(alto * factor)), Image.LANCZOS)
    imagen = ImageOps.autocontrast(imagen)
    imagen = imagen.filter(ImageFilter.SHARPEN)
    imagen = imagen.point(lambda p: 255 if p > 150 else 0)
    return imagen


def _mejor_candidato(texto: str) -> str | None:
    candidatos = _PATRON_SERIAL.findall(texto.upper())
    if not candidatos:
        return None
    return max(candidatos, key=len)


async def extraer_serie(imagen_bytes: bytes) -> str | None:
    """Devuelve el número de serie en mayúsculas, o None si no se pudo
    leer con confianza (ni por código de barras ni por texto)."""
    try:
        imagen = Image.open(io.BytesIO(imagen_bytes))

        # 1) Código de barras primero — mucho más confiable.
        if _ZBAR_DISPONIBLE:
            codigos = decodificar_barras(imagen)
            if codigos:
                valor = codigos[0].data.decode("utf-8", errors="ignore").strip().upper()
                if valor:
                    return valor

        # 2) Respaldo: leer el texto impreso con Tesseract, probando
        # varios modos de segmentación (una etiqueta con código de
        # barras + texto no es un bloque uniforme).
        imagen_prep = _preprocesar(imagen)
        mejor = None
        for psm in (6, 11, 7):
            texto = pytesseract.image_to_string(imagen_prep, config=f"--psm {psm}")
            candidato = _mejor_candidato(texto)
            if candidato and (mejor is None or len(candidato) > len(mejor)):
                mejor = candidato
        return mejor
    except Exception:
        logger.exception("Fallo leyendo la serie del panel.")
        return None
