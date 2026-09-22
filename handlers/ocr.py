"""
Lee el número de serie de la foto de una etiqueta de panel usando
Tesseract — OCR libre y gratuito que corre localmente, sin ninguna API
de pago.

Nota importante: Tesseract lee bastante peor que un modelo de visión en
fotos reales de celular (ángulos, reflejos de la etiqueta, texto pequeño
junto a un código de barras). El flujo de /salida ya contempla pedir que
se repita la foto, y también permite escribir la serie a mano si la
lectura automática sigue fallando — revisa handlers/salida.py.
"""
import io
import logging
import re

import pytesseract
from PIL import Image, ImageOps, ImageFilter

logger = logging.getLogger(__name__)

# Un número de serie de panel suele ser una cadena alfanumérica larga,
# sin espacios. Ajusta este patrón si tus paneles usan otro formato
# (por ejemplo, si siempre empiezan con letras fijas de la marca).
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
    leer con confianza en ninguno de los modos probados."""
    try:
        imagen = Image.open(io.BytesIO(imagen_bytes))
        imagen = _preprocesar(imagen)

        mejor = None
        # Prueba varios modos de segmentación de Tesseract, porque una
        # etiqueta con código de barras + texto no es un bloque uniforme.
        for psm in (6, 11, 7):
            texto = pytesseract.image_to_string(imagen, config=f"--psm {psm}")
            candidato = _mejor_candidato(texto)
            if candidato and (mejor is None or len(candidato) > len(mejor)):
                mejor = candidato
        return mejor
    except Exception:
        logger.exception("Fallo leyendo la serie con Tesseract.")
        return None
