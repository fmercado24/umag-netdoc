"""Importar el levantamiento de un edificio subiendo sus planillas CSV desde el visor.

Hace lo mismo que ``importar_edificio`` con los CSV dejados en ``data/<código>/``:
la misma lectura tolerante, la ubicación de cada elemento en su sala y las fechas
del levantamiento. Se hace en dos pasos, con los mismos archivos:

1. **Revisar** (``ensayo``): se importa todo dentro de la transacción y luego se
   descarta. El informe dice qué se crearía, qué se corrigió y qué quedaría sin
   ubicar, sin cambiar nada.
2. **Importar**: lo mismo, ahora de verdad.

Cada archivo debe llamarse según la nomenclatura: ``<código>-p<piso>[-t<tramo>].csv``
para el equipamiento de un piso o tramo, y ``<código>-<planilla>.csv`` para las
demás (``FIJAS``). Lo mal nombrado se rechaza diciendo, si se puede deducir, cómo
debería llamarse.

Sin elementos se importa todo; con elementos se suma lo nuevo, como
``importar_edificio --agregar``: un tramo ya importado se omite y no se toca lo
ubicado ni lo corregido en el visor. Reemplazar lo importado (``--recargar``) sigue
siendo solo de la terminal, porque borra las posiciones y el historial.

Se exige que el edificio tenga sus planos, con las salas ya leídas: es lo que
permite ubicar cada elemento en su sala al importarlo, y con elementos los planos
ya no se cargan desde el visor.

Las planillas importadas se guardan en ``media/planillas/<EDIFICIO>/``, que se
respalda con la base y no se sirve en ``/media``. La importación siguiente las usa
junto con las que llegan, igual que la carpeta ``data/<código>/``: así la planilla
de un tramo nuevo encuentra la leyenda de VLANs o las excepciones de lámina que ya
se habían subido. Si se reemplaza una, la anterior queda en ``anteriores/``.
"""

from __future__ import annotations

import datetime as dt
import difflib
import re
import shutil
import tempfile
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import configuracion
from app.models import Edificio, Piso, Plano
from app.scripts.importar_edificio import (
    Importador,
    Resultado,
    contar_elementos,
    dir_datos_de,
)
from app.servicios.carga_planos import describir_destino
from app.servicios.lectura_recintos import EN_CURSO
from app.servicios.levantamientos import (
    ArchivoLevantamientoInvalido,
    aplicar_levantamientos,
    leer_levantamientos,
    ruta_levantamientos,
)
from app.servicios.planos import sugerir_nombre_lamina
from app.servicios.recintos import lineas_informe, sincronizar_y_ubicar

#: Las planillas de nombre fijo, ``<código>-<nombre>.csv``, y qué traen.
FIJAS: dict[str, str] = {
    "puntos-de-datos": "Puntos de datos del edificio",
    "vlans": "Leyenda de VLANs",
    "laminas": "Excepciones de lámina",
    "levantamiento": "Fechas de las visitas a terreno",
    "recintos": "Salas de los planos, revisadas",
    "global": "Inventario global, para contrastar",
}
#: El piso con dos dígitos y el tramo sin ceros a la izquierda, como los planos.
RE_EQUIPAMIENTO = re.compile(r"p(\d{2})(?:-t([1-9]\d*))?")
RE_NOMBRE = re.compile(r"^([a-z0-9]+)-(.+)\.csv$")
NOMENCLATURA = "<edificio>-p<piso>[-t<tramo>].csv"
LIBROS = {"xlsx", "xlsm", "xls", "ods", "numbers"}


class CargaNoPermitida(Exception):
    """El edificio todavía no puede recibir planillas desde el visor."""


class PlanillasRechazadas(Exception):
    """Algún archivo no sigue la nomenclatura o no se puede leer."""


@dataclass(frozen=True)
class Revision:
    """Lo que dice el nombre de un archivo."""

    archivo: str
    #: Nombre con que se importa; nulo si se rechaza.
    nombre: str | None = None
    #: «Equipamiento: Piso 1, tramo 1», «Puntos de datos del edificio»…
    contenido: str | None = None
    #: Por qué se rechaza; nulo si se acepta.
    error: str | None = None
    #: El nombre que debería tener, si se pudo deducir del original.
    sugerencia: str | None = None


@dataclass
class Informe:
    ensayo: bool
    #: «nuevo» si el edificio no tenía elementos; «agregar» si ya tenía.
    modo: str
    aceptados: list[Revision]
    rechazados: list[Revision]
    #: Planillas ya guardadas que se usan junto con las que llegaron.
    guardadas: list[str] = field(default_factory=list)
    #: Por qué todavía no se puede importar de verdad (solo en el ensayo).
    motivo: str | None = None
    resultado: Resultado | None = None
    advertencias: list[str] = field(default_factory=list)
    levantamiento: str | None = None
    #: El informe de ubicación en las salas, como en la terminal.
    ubicacion: list[str] = field(default_factory=list)
    ubicados: int = 0
    sin_ubicar: int = 0


# --------------------------------------------------------------------------
# Nombres
# --------------------------------------------------------------------------
def _contenido(resto: str) -> str | None:
    """Qué trae la planilla según lo que sigue al código del edificio."""
    if resto in FIJAS:
        return FIJAS[resto]
    if coincidencia := RE_EQUIPAMIENTO.fullmatch(resto):
        piso, tramo = coincidencia.groups()
        return "Equipamiento: " + describir_destino(f"P{piso}", f"T{tramo}" if tramo else None)
    return None


def _sugerir(prefijo: str, nombre: str) -> str | None:
    """El nombre estándar deducido de uno que no lo es: «Puntos de datos.csv»,
    «cadi_vlan.csv», «CADI P1 T2.csv», «cadi 1er piso tramo 2.csv»."""
    texto = unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode().lower()
    raiz = texto.rsplit(".", 1)[0] if "." in texto else texto
    fichas = [f for f in re.split(r"[\s_.\-()]+", raiz) if f and not f.isdecimal()]
    if fichas and fichas[0] == prefijo:
        fichas = fichas[1:]
    parecida = difflib.get_close_matches("-".join(fichas), FIJAS, n=1, cutoff=0.75)
    if parecida:
        return f"{prefijo}-{parecida[0]}.csv"
    return sugerir_nombre_lamina(f"{raiz}.csv", edificio=prefijo)


def revisar(codigo_edificio: str, archivo: str) -> Revision:
    """Si el nombre sigue la nomenclatura y es de este edificio. Da igual escribirlo
    en mayúsculas o minúsculas: se importa con el nombre en minúsculas."""
    prefijo = codigo_edificio.lower()
    nombre = archivo.replace("\\", "/").rsplit("/", 1)[-1].strip().lower()
    extension = nombre.rsplit(".", 1)[-1] if "." in nombre else ""
    if extension in LIBROS:
        return Revision(
            archivo,
            error="Es un libro de cálculo: guarde cada hoja como «CSV UTF-8» con el nombre que "
            "indica la hoja Instrucciones de la plantilla.",
        )
    if extension != "csv":
        return Revision(archivo, error="Solo se aceptan planillas CSV.")
    if coincidencia := RE_NOMBRE.match(nombre):
        edificio, resto = coincidencia.groups()
        contenido = _contenido(resto)
        if contenido and edificio != prefijo:
            return Revision(
                archivo, error=f"Es del edificio {edificio.upper()}, no de {codigo_edificio.upper()}."
            )
        if contenido:
            return Revision(archivo, nombre=nombre, contenido=contenido)
    sugerencia = _sugerir(prefijo, nombre)
    return Revision(
        archivo,
        error="No sigue la nomenclatura." if sugerencia else _sin_sugerencia(prefijo),
        sugerencia=sugerencia,
    )


def _sin_sugerencia(prefijo: str) -> str:
    return (
        f"No sigue la nomenclatura: {prefijo}-p01-t1.csv para el equipamiento de un tramo, "
        f"{prefijo}-p01.csv para un piso completo o {prefijo}-<planilla>.csv para las demás."
    )


def _revisar_contenido(datos: bytes) -> str | None:
    if not datos.strip():
        return "Está vacío."
    if datos[:4] == b"PK\x03\x04":
        return "Es un libro de Excel con extensión .csv: ábralo y guárdelo como «CSV UTF-8»."
    if b"\x00" in datos:
        return "No es texto CSV: guárdelo como «CSV UTF-8», no como texto Unicode."
    return None


def ejemplos(codigo_edificio: str) -> list[dict[str, str]]:
    """Los nombres que se aceptan, para mostrarlos antes de elegir archivos."""
    p = codigo_edificio.lower()
    return [
        {"nombre": f"{p}-p01-t1.csv", "contenido": _contenido("p01-t1") or ""},
        {"nombre": f"{p}-p02.csv", "contenido": _contenido("p02") or ""},
        {"nombre": f"{p}-p00.csv", "contenido": _contenido("p00") or ""},
    ] + [{"nombre": f"{p}-{nombre}.csv", "contenido": texto} for nombre, texto in FIJAS.items()]


# --------------------------------------------------------------------------
# Estado
# --------------------------------------------------------------------------
def _carpeta(codigo_edificio: str) -> Path:
    return configuracion.dir_planillas / codigo_edificio.upper()


def guardadas(codigo_edificio: str) -> dict[str, Path]:
    """Las planillas que ya tiene el edificio: las de ``data/<código>/`` y,
    encima, las importadas desde el visor."""
    encontradas: dict[str, Path] = {}
    for carpeta in (dir_datos_de(codigo_edificio), _carpeta(codigo_edificio)):
        if not carpeta.is_dir():
            continue
        for ruta in sorted(carpeta.glob("*.csv")):
            revision = revisar(codigo_edificio, ruta.name)
            if revision.nombre:
                encontradas[revision.nombre] = ruta
    return encontradas


def motivo_para_no_importar(sesion: Session, edificio: Edificio) -> str | None:
    """Por qué todavía no se pueden importar planillas desde el visor, o None."""
    planos = sesion.scalars(
        select(Plano)
        .join(Piso, Plano.piso_id == Piso.id)
        .where(Piso.edificio_id == edificio.id, Plano.vigente.is_(True))
    ).all()
    if not planos:
        return (
            f"Primero cargue los planos de {edificio.codigo}: con ellos cada elemento queda en su "
            "sala al importarlo, y con elementos los planos ya no se cargan desde el visor."
        )
    leyendo = sum(1 for plano in planos if plano.lectura_recintos in EN_CURSO)
    if leyendo:
        return (
            f"Todavía se están leyendo las salas de {leyendo} plano(s). Importe cuando termine "
            "(unos minutos), para que cada elemento quede en su sala."
        )
    return None


def modo(sesion: Session, edificio: Edificio) -> str:
    """Cuenta también los eliminados: siguen siendo del edificio y se pueden restaurar."""
    return "agregar" if contar_elementos(sesion, edificio.codigo) else "nuevo"


# --------------------------------------------------------------------------
# Importación
# --------------------------------------------------------------------------
def importar(
    sesion: Session,
    edificio: Edificio,
    archivos: list[tuple[str, bytes]],
    *,
    ensayo: bool,
    usuario: str | None = None,
) -> Informe:
    """Revisa los archivos e importa los aceptados; en el ensayo, lo descarta.

    Fuera del ensayo lanza ``PlanillasRechazadas`` si algún archivo se rechaza y
    ``CargaNoPermitida`` si el edificio aún no puede recibirlas: no se importa nada
    a medias.
    """
    revisiones: list[Revision] = []
    aceptadas: dict[str, bytes] = {}
    for archivo, datos in archivos:
        revision = revisar(edificio.codigo, archivo)
        if revision.nombre in aceptadas:
            revision = Revision(archivo, error=f"Ya viene otro archivo llamado «{revision.nombre}».")
        elif revision.nombre and (error := _revisar_contenido(datos)):
            revision = Revision(archivo, error=error)
        elif revision.nombre:
            aceptadas[revision.nombre] = datos
        revisiones.append(revision)
    rechazados = [r for r in revisiones if r.error]
    motivo = motivo_para_no_importar(sesion, edificio)
    if not ensayo:
        if rechazados:
            raise PlanillasRechazadas(
                "No se importó nada: "
                + "; ".join(f"«{r.archivo}»: {r.error}" for r in rechazados)
            )
        if not aceptadas:
            raise PlanillasRechazadas("No llegó ninguna planilla.")
        if motivo:
            raise CargaNoPermitida(motivo)

    informe = Informe(
        ensayo=ensayo,
        modo=modo(sesion, edificio),
        aceptados=[r for r in revisiones if not r.error],
        rechazados=rechazados,
        motivo=motivo if ensayo else None,
    )
    if not aceptadas:
        return informe

    previas = guardadas(edificio.codigo)
    informe.guardadas = sorted(nombre for nombre in previas if nombre not in aceptadas)
    with tempfile.TemporaryDirectory(prefix="netdoc-planillas-") as temporal:
        carpeta = Path(temporal)
        for nombre, ruta in previas.items():
            shutil.copyfile(ruta, carpeta / nombre)
        for nombre, datos in aceptadas.items():
            (carpeta / nombre).write_bytes(datos)
        _importar(sesion, edificio, carpeta, informe, usuario or "importacion")

    if ensayo:
        sesion.rollback()
    else:
        sesion.flush()
        _guardar(edificio.codigo, aceptadas)
    return informe


def _importar(
    sesion: Session, edificio: Edificio, carpeta: Path, informe: Informe, usuario: str
) -> None:
    """Lo mismo que ``importar_edificio`` hace después de leer la carpeta."""
    resultado = Importador(
        sesion, carpeta, edificio.codigo, agregar=informe.modo == "agregar", usuario=usuario
    ).ejecutar()
    informe.resultado = resultado
    advertencias = list(resultado.advertencias)

    ruta = ruta_levantamientos(carpeta, edificio.codigo)
    try:
        visitas = leer_levantamientos(ruta)
    except ArchivoLevantamientoInvalido as exc:
        advertencias.append(f"{ruta.name}: no se aplicó. {exc}")
    else:
        if visitas:
            levantamiento = aplicar_levantamientos(sesion, edificio, visitas)
            informe.levantamiento = (
                f"{levantamiento.visitas_nuevas} visita(s) nueva(s) en la bitácora; fecha del "
                f"último levantamiento en {levantamiento.elementos_fechados} elementos"
            )

    # Sin planos, o mientras se leen sus salas, no hay dónde ubicar (solo en el ensayo).
    if informe.motivo is None:
        recintos, ubicacion = sincronizar_y_ubicar(sesion, edificio, carpeta)
        informe.ubicacion = lineas_informe(recintos, ubicacion)
        informe.ubicados = ubicacion.ubicados + ubicacion.junto_a
        informe.sin_ubicar = len(ubicacion.sin_numero) + len(ubicacion.no_encontrados)

    # La carpeta es temporal: los avisos hablan de las planillas, no de dónde se leyeron.
    informe.advertencias = [a.replace(str(carpeta), "las planillas") for a in advertencias]
    informe.ubicacion = [linea.replace(str(carpeta), "las planillas") for linea in informe.ubicacion]


def _guardar(codigo_edificio: str, aceptadas: dict[str, bytes]) -> None:
    carpeta = _carpeta(codigo_edificio)
    carpeta.mkdir(parents=True, exist_ok=True)
    marca = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    for nombre, datos in aceptadas.items():
        destino = carpeta / nombre
        if destino.is_file():
            if destino.read_bytes() == datos:
                continue
            anteriores = carpeta / "anteriores"
            anteriores.mkdir(exist_ok=True)
            destino.replace(anteriores / f"{marca}-{nombre}")
        destino.write_bytes(datos)
