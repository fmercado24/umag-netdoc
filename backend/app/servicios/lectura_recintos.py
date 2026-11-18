"""Las salas de los planos cargados desde el visor, leídas con OCR.

Al confirmar una carga de planos, el sistema lee los rótulos de sala de cada
uno con ``app.servicios.ocr_recintos``, tal como los escribe el plano: «1083»
en el CADI, «09» o «25A» en la Biblioteca. Los guarda como recintos del plano,
y cada elemento con ese número de recinto queda ubicado en su sala.

Se lee en segundo plano, en un proceso aparte y de a un plano: usa cerca de
1 GB de memoria y toma alrededor de un minuto por plano. El proceso termina al
acabar, así que la memoria vuelve al sistema y un fallo del OCR no se lleva
consigo a la API.

``plano.lectura_recintos`` dice en qué va: pendiente, leyendo, lista, fallida o
sin_ocr (el servidor no tiene el OCR instalado). Al arrancar, el sistema
retoma lo que quedó pendiente o a medias, y lo que esperaba el OCR si ya está.
"""

from __future__ import annotations

import importlib.util
import logging
import multiprocessing
import threading
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select

from app.core.config import configuracion
from app.db.session import sesion_de_trabajo
from app.models import OrigenCambio, Plano
from app.servicios.ocr_recintos import LecturaDeLamina
from app.servicios.recintos import (
    FilaRecinto,
    InformeRecintos,
    es_rotulo_de_rack,
    huella_lamina,
    reemplazar_recintos,
    ubicar_pendientes,
)

registro = logging.getLogger(__name__)

PENDIENTE = "pendiente"
LEYENDO = "leyendo"
LISTA = "lista"
FALLIDA = "fallida"
SIN_OCR = "sin_ocr"
#: Mientras está en uno de estos, no se puede pedir otra lectura.
EN_CURSO = frozenset({PENDIENTE, LEYENDO})

AVISO_SIN_OCR = (
    "El servidor no tiene instalado el OCR que lee las salas de los planos. "
    "Instálelo con sudo ./instalar-servidor.sh (o, en desarrollo, "
    "pip install -r requirements-ocr.txt) y reinicie NetDoc: las leerá solo."
)

#: Un OCR a la vez: cada uno usa cerca de 1 GB de memoria.
_uno_a_la_vez = threading.Lock()


def hay_ocr() -> bool:
    return importlib.util.find_spec("rapidocr_onnxruntime") is not None


def puede_leer() -> str | None:
    """Por qué este servidor no puede leer salas, o None si puede."""
    if not configuracion.leer_recintos:
        return "La lectura de salas con OCR está desactivada en este servidor (NETDOC_LEER_RECINTOS)."
    if not hay_ocr():
        return AVISO_SIN_OCR
    return None


def marcar_para_leer(plano: Plano) -> bool:
    """Lo deja pendiente de leer, si este servidor lee salas."""
    if not configuracion.leer_recintos:
        return False
    plano.lectura_recintos, plano.lectura_aviso = PENDIENTE, None
    return True


@dataclass(frozen=True)
class Encargo:
    """Lo que el proceso aparte necesita para leer un plano."""

    ruta: str
    ancho: int
    alto: int
    piso: str
    #: Lo leído en las otras láminas del piso, que no se vuelve a buscar.
    ya_en_el_piso: tuple[str, ...]
    huella: str


def _leer_en_proceso(encargo: Encargo) -> LecturaDeLamina:
    """En el proceso aparte: sus errores vuelven como RuntimeError, que se
    capturan sin importar el OCR ni libvips en la API."""
    try:
        from app.servicios.ocr_recintos import crear_ocr, leer_recintos_de_lamina

        return leer_recintos_de_lamina(
            Path(encargo.ruta),
            encargo.ancho,
            encargo.alto,
            encargo.piso,
            crear_ocr(),
            ya_en_el_piso=frozenset(encargo.ya_en_el_piso),
        )
    except Exception as exc:  # noqa: BLE001 - lo que sea, vuelve como texto
        raise RuntimeError(f"{type(exc).__name__}: {exc}") from None


def leer(encargo: Encargo) -> LecturaDeLamina:
    """Lee el plano en un proceso aparte, que termina al acabar."""
    contexto = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=1, mp_context=contexto) as proceso:
        return proceso.submit(_leer_en_proceso, encargo).result()


def _preparar(plano_id: int) -> Encargo | None:
    with sesion_de_trabajo(escribe=True) as sesion:
        plano = sesion.get(Plano, plano_id)
        if plano is None or not plano.vigente:
            return None
        if (motivo := puede_leer()) is not None:
            plano.lectura_recintos, plano.lectura_aviso = SIN_OCR, motivo[:300]
            return None
        ruta = configuracion.dir_media / plano.archivo
        if not ruta.is_file():
            plano.lectura_recintos, plano.lectura_aviso = FALLIDA, "No se encontró el archivo del plano."
            return None
        otros = sorted(
            {
                recinto.numero
                for otro in plano.piso.planos
                if otro.vigente and otro.id != plano.id
                for recinto in otro.recintos
                if not es_rotulo_de_rack(recinto.numero)
            }
        )
        plano.lectura_recintos, plano.lectura_aviso = LEYENDO, None
        return Encargo(
            ruta=str(ruta),
            ancho=plano.ancho_px,
            alto=plano.alto_px,
            piso=plano.piso.codigo,
            ya_en_el_piso=tuple(otros),
            huella=huella_lamina(ruta.read_bytes()),
        )


def _terminar(plano_id: int, estado: str, aviso: str) -> None:
    with sesion_de_trabajo(escribe=True) as sesion:
        if (plano := sesion.get(Plano, plano_id)) is not None:
            plano.lectura_recintos, plano.lectura_aviso = estado, aviso[:300]


def describir_lectura(salas: int, racks: int) -> str:
    if not salas and not racks:
        return "No se encontraron rótulos de sala en el plano: ubique los elementos con un clic."
    partes = [f"{salas} sala{'s' if salas != 1 else ''}"] if salas else []
    if racks:
        partes.append(f"{racks} rack{'s' if racks != 1 else ''}")
    return " y ".join(partes) + (" leídos del plano" if racks else " leídas del plano")


def _guardar(plano_id: int, encargo: Encargo, lectura: LecturaDeLamina) -> None:
    with sesion_de_trabajo(escribe=True) as sesion:
        plano = sesion.get(Plano, plano_id)
        ruta = Path(encargo.ruta)
        if plano is None or not plano.vigente:
            registro.info("Salas de %s descartadas: el plano se quitó o se reemplazó", ruta.name)
            return
        if not ruta.is_file() or huella_lamina(ruta.read_bytes()) != encargo.huella:
            plano.lectura_recintos, plano.lectura_aviso = PENDIENTE, None
            return
        filas = [
            FilaRecinto(ruta.name, r.numero, r.nombre, r.x, r.y, encargo.huella)
            for r in [*lectura.recintos, *lectura.racks]
        ]
        reemplazar_recintos(plano, filas, InformeRecintos())
        plano.lectura_recintos = LISTA
        plano.lectura_aviso = describir_lectura(len(lectura.recintos), len(lectura.racks))
        sesion.flush()
        # Lo que ya tenía número de recinto queda en su sala.
        ubicar_pendientes(sesion, plano.piso.edificio, origen=OrigenCambio.SISTEMA)


def leer_recintos_del_plano(plano_id: int) -> None:
    """Tarea de fondo: lee las salas del plano y las deja como sus recintos.

    Si el plano se quita o se reemplaza mientras se lee, lo leído se descarta.
    """
    if not configuracion.leer_recintos:
        return
    with _uno_a_la_vez:
        encargo = _preparar(plano_id)
        if encargo is None:
            return
        inicio = time.monotonic()
        try:
            lectura = leer(encargo)
        except Exception as exc:  # noqa: BLE001 - un fallo del OCR no debe tumbar la API
            registro.warning("No se pudieron leer las salas de %s", encargo.ruta, exc_info=True)
            _terminar(plano_id, FALLIDA, f"No se pudieron leer las salas del plano: {exc}")
            return
        _guardar(plano_id, encargo, lectura)
        registro.info(
            "Salas de %s: %d en %.0f s",
            Path(encargo.ruta).name,
            len(lectura.recintos),
            time.monotonic() - inicio,
        )


def retomar_pendientes() -> None:
    """Al arrancar: lee lo que quedó pendiente o a medias, y lo que esperaba
    el OCR si ahora está instalado."""
    if not configuracion.leer_recintos:
        return
    estados = [PENDIENTE, LEYENDO] + ([SIN_OCR] if hay_ocr() else [])
    try:
        with sesion_de_trabajo() as sesion:
            ids = sesion.scalars(
                select(Plano.id)
                .where(Plano.vigente.is_(True), Plano.lectura_recintos.in_(estados))
                .order_by(Plano.id)
            ).all()
    except Exception:  # noqa: BLE001 - p. ej. una base aún sin migrar
        registro.warning("No se pudo revisar qué planos esperan que se lean sus salas", exc_info=True)
        return
    for plano_id in ids:
        leer_recintos_del_plano(plano_id)


def retomar_en_segundo_plano() -> threading.Thread:
    hilo = threading.Thread(target=retomar_pendientes, name="lectura-de-salas", daemon=True)
    hilo.start()
    return hilo
