"""Teselas de los planos: la lámina pre-dibujada en una pirámide de imágenes.

Una lámina exportada desde CAD trae cientos de miles de trazos (las del CADI,
hasta 180 000 en 30 MB), y el navegador vuelve a dibujarlos todos cada vez
que necesita un pedazo nuevo del plano: al moverlo o acercarlo, el visor se
arrastra. Como en un mapa web, la lámina se dibuja una sola vez en teselas de
256×256 por nivel de acercamiento, y el visor solo muestra imágenes ya hechas.

Cada nivel duplica la escala del anterior, igual que los niveles del visor
(Leaflet con ``CRS.Simple``: en el nivel ``z`` una unidad del plano mide
``2**z`` píxeles). El nivel más detallado se elige para que la lámina mida
unos ``ANCHO_OBJETIVO`` píxeles de ancho: en las del CADI deja legibles los
rótulos de los puntos de datos. Más allá, el visor amplía esas teselas.

Las teselas viven en ``media/teselas/<nombre del archivo del plano>/`` con
``teselas.json``, que el visor necesita para alinear sus niveles con los de
la pirámide. Ese archivo se escribe al final: sin él, la pirámide no cuenta
como lista y el visor sigue mostrando la lámina original.
"""

from __future__ import annotations

import json
import logging
import math
import multiprocessing
import shutil
import time
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from dataclasses import asdict, dataclass
from pathlib import Path

from app.core.config import configuracion

registro = logging.getLogger(__name__)

TAMANO_TESELA = 256
ANCHO_OBJETIVO = 12_000
#: Límites del nivel más detallado: de 1/4 a 16 píxeles por unidad del plano.
ZOOM_MAX_MINIMO, ZOOM_MAX_MAXIMO = -2, 4
CALIDAD_WEBP = 80
ARCHIVO_INFO = "teselas.json"


@dataclass(frozen=True)
class InfoTeselas:
    """Lo que el visor necesita para pedir las teselas de una lámina."""

    #: Ruta bajo ``/media`` con ``{z}``, ``{x}`` e ``{y}`` para el visor.
    url: str
    #: Nivel del visor que corresponde al nivel más detallado de la pirámide.
    zoom_max: int
    #: Niveles de la pirámide (el 0 cabe en una tesela).
    niveles: int
    tamano: int = TAMANO_TESELA


def dir_teselas(archivo: str) -> Path:
    """Carpeta de las teselas del plano guardado en ``media/<archivo>``."""
    return configuracion.dir_media / "teselas" / Path(archivo).stem


def leer_teselas(archivo: str) -> InfoTeselas | None:
    """Las teselas del plano, o None si aún no se generaron."""
    try:
        datos = json.loads((dir_teselas(archivo) / ARCHIVO_INFO).read_text(encoding="utf-8"))
        return InfoTeselas(**datos)
    except (OSError, ValueError, TypeError):
        return None


def zoom_maximo(ancho_px: int) -> int:
    """Nivel del visor más detallado: la lámina mide unos ANCHO_OBJETIVO px."""
    zoom = math.floor(math.log2(ANCHO_OBJETIVO / ancho_px))
    return max(ZOOM_MAX_MINIMO, min(ZOOM_MAX_MAXIMO, zoom))


def generar_teselas(archivo: str, ancho_px: int) -> InfoTeselas:
    """Dibuja la pirámide de teselas del plano ``media/<archivo>``.

    ``ancho_px`` es el ancho del plano en sus propias unidades (el sistema de
    coordenadas de las posiciones), no el del archivo: la pirámide se escala
    para que una unidad mida exactamente ``2**zoom_max`` píxeles.
    """
    # libvips se carga solo aquí: el resto del sistema funciona sin teselas.
    import pyvips

    # Cada lámina se dibuja una vez: guardar resultados intermedios solo
    # acumula memoria de una lámina a la siguiente.
    pyvips.cache_set_max(0)

    origen = configuracion.dir_media / archivo
    vectorial = origen.suffix.lower() == ".svg"
    # Abrirlo no lo dibuja: solo lee el tamaño natural del archivo.
    natural = pyvips.Image.new_from_file(str(origen))
    zoom = zoom_maximo(ancho_px)
    if not vectorial:
        # Agrandar una imagen no le agrega detalle: el nivel más detallado
        # queda en su resolución propia, y más allá amplía el visor.
        propio = math.floor(math.log2(natural.width / ancho_px))
        zoom = max(ZOOM_MAX_MINIMO, min(zoom, propio))
    factor = 2.0**zoom * ancho_px / natural.width
    if vectorial:
        # Un vector se vuelve a dibujar a la escala justa, sin perder nitidez.
        # Antes se suelta el primero: cada uno retiene el SVG entero en memoria.
        del natural
        imagen = pyvips.Image.new_from_file(str(origen), scale=factor, access="sequential")
    else:
        imagen = natural.resize(factor)
    if imagen.hasalpha():
        imagen = imagen.flatten(background=[255] * (imagen.bands - 1))

    # Se arma aparte y se cambia de una vez: nunca queda a medias a la vista.
    destino = dir_teselas(archivo)
    temporal = destino.with_name(destino.name + ".generando")
    shutil.rmtree(temporal, ignore_errors=True)
    temporal.mkdir(parents=True)
    imagen.dzsave(
        str(temporal / "piramide"),
        layout="google",
        tile_size=TAMANO_TESELA,
        overlap=0,
        suffix=f".webp[Q={CALIDAD_WEBP}]",
        # También las teselas en blanco: si faltan, el visor las pide igual.
        skip_blanks=-1,
        background=[255] * min(imagen.bands, 3),
    )
    piramide = temporal / "piramide"
    niveles = 1 + max(int(n.name) for n in piramide.iterdir() if n.name.isdigit())
    info = InfoTeselas(
        url=f"teselas/{destino.name}/{{z}}/{{y}}/{{x}}.webp", zoom_max=zoom, niveles=niveles
    )
    for nivel in piramide.iterdir():
        nivel.rename(temporal / nivel.name)
    piramide.rmdir()
    (temporal / ARCHIVO_INFO).write_text(json.dumps(asdict(info)), encoding="utf-8")

    shutil.rmtree(destino, ignore_errors=True)
    temporal.rename(destino)
    return info


def _generar_en_proceso(archivo: str, ancho_px: int) -> InfoTeselas:
    """``generar_teselas`` para el proceso aparte: sus errores vuelven como
    RuntimeError, que sí se puede capturar sin importar libvips."""
    try:
        import pyvips
    except (ImportError, OSError) as exc:
        raise RuntimeError(f"libvips no está disponible: {exc}") from None
    try:
        return generar_teselas(archivo, ancho_px)
    except pyvips.Error as exc:
        raise RuntimeError(str(exc)) from None


def asegurar_teselas(archivo: str, ancho_px: int) -> InfoTeselas | None:
    """Genera las teselas si faltan. Un fallo no impide usar el plano: el
    visor muestra la lámina original, solo que más lento.

    Se dibujan en un proceso aparte, que termina al acabar. libvips retiene
    cerca de 1 GB con una lámina grande y el proceso no lo devuelve al
    sistema: así cada lámina parte de cero, y un fallo de la biblioteca no se
    lleva consigo a la API.
    """
    if (info := leer_teselas(archivo)) is not None or not configuracion.teselas:
        return info
    inicio = time.monotonic()
    contexto = multiprocessing.get_context("spawn")
    try:
        with ProcessPoolExecutor(max_workers=1, mp_context=contexto) as proceso:
            info = proceso.submit(_generar_en_proceso, archivo, ancho_px).result()
    except (RuntimeError, OSError, ValueError, BrokenProcessPool):
        registro.warning("No se pudieron generar las teselas de %s", archivo, exc_info=True)
        return None
    registro.info("Teselas de %s en %.1f s", archivo, time.monotonic() - inicio)
    return info
