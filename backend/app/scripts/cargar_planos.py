"""Carga las láminas de un edificio que aún no tienen plano vigente.

    python -m app.scripts.cargar_planos              # todos los edificios con carpeta
    python -m app.scripts.cargar_planos ING CADI     # solo esos
    python -m app.scripts.cargar_planos ING --planos /otra/carpeta

Las láminas se buscan en ``data/<código en minúsculas>/planos`` y se
reconocen por nombre, de dos formas:

* compacta, como las planillas: ``ing-p01-t2.svg`` (tramo T2 del piso P01),
  ``ing-p04.svg`` (piso P04 completo), ``ing-p00.svg`` (subterráneo);
* descriptiva, como las entregó la DSI para el CADI: «cadi 1er piso tramo
  2.svg», «cadi 4to piso.svg», «cadi subterraneo.svg».

Un piso–tramo que ya tiene plano vigente no se toca, así que el script puede
correrse cada vez que se inicia el sistema. Una versión nueva de una lámina ya
cargada se sube con el endpoint de planos. Antes de cargarlas conviene pasar
las láminas por ``app.scripts.preparar_laminas`` (limpieza y orientación).

Las dimensiones del plano se toman del propio SVG: en la primera carga todavía
no hay posiciones que dependan de ellas.
"""

from __future__ import annotations

import argparse
import re
import unicodedata
from pathlib import Path
from xml.etree import ElementTree

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import SesionLocal
from app.models import Edificio, Piso, Tramo
from app.scripts.importar_edificio import DIR_DATA
from app.servicios.planos import PlanoRechazado, guardar_plano, sanear_svg


def dir_planos_de(codigo_edificio: str) -> Path:
    return DIR_DATA / codigo_edificio.lower() / "planos"


RE_PISO = re.compile(r"(\d+)\s*[a-z]*\s+piso")
RE_TRAMO = re.compile(r"tramo\s*(\d+)")
RE_COMPACTO = re.compile(r"(?:^|[-_ ])p(\d{1,2})(?:-t(\d+))?\.svg$")


def ubicar_lamina(nombre_archivo: str) -> tuple[str, str | None] | None:
    """Piso y tramo que cubre la lámina según su nombre, o None si no se reconoce."""
    base = unicodedata.normalize("NFKD", nombre_archivo).encode("ascii", "ignore").decode()
    base = base.lower()
    if compacto := RE_COMPACTO.search(base):
        tramo = compacto.group(2)
        return f"P{int(compacto.group(1)):02d}", f"T{int(tramo)}" if tramo else None
    if "subterraneo" in base:
        piso = "P00"
    elif coincidencia := RE_PISO.search(base):
        piso = f"P{int(coincidencia.group(1)):02d}"
    else:
        return None
    tramo = RE_TRAMO.search(base)
    return piso, f"T{int(tramo.group(1))}" if tramo else None


def dimensiones_svg(contenido: bytes) -> tuple[int, int]:
    """Ancho y alto del SVG en sus propias unidades (las del ``viewBox``)."""
    raiz = ElementTree.fromstring(contenido)
    caja = raiz.get("viewBox")
    if caja:
        _, _, ancho, alto = (float(v) for v in re.split(r"[\s,]+", caja.strip()))
    else:
        ancho, alto = float(raiz.get("width", 0)), float(raiz.get("height", 0))
    if ancho <= 0 or alto <= 0:
        raise ValueError("el SVG no declara viewBox ni width/height")
    return round(ancho), round(alto)


def cargar(sesion: Session, dir_planos: Path, codigo_edificio: str) -> tuple[int, list[str]]:
    codigo_edificio = codigo_edificio.upper()
    edificio = sesion.scalar(select(Edificio).where(Edificio.codigo == codigo_edificio))
    if edificio is None:
        raise SystemExit(
            f"No existe el edificio {codigo_edificio} en el catálogo "
            "(ver docs/guia-nuevo-edificio.md)"
        )

    cargados = 0
    omitidos: list[str] = []
    for ruta in sorted(dir_planos.glob("*.svg")):
        ubicacion = ubicar_lamina(ruta.name)
        if ubicacion is None:
            omitidos.append(f"{ruta.name}: el nombre no indica el piso")
            continue
        codigo_piso, codigo_tramo = ubicacion

        piso = sesion.scalar(
            select(Piso).where(Piso.edificio_id == edificio.id, Piso.codigo == codigo_piso)
        )
        if piso is None:
            omitidos.append(f"{ruta.name}: el piso {codigo_piso} no existe en el sistema")
            continue
        tramo = None
        if codigo_tramo:
            tramo = sesion.scalar(
                select(Tramo).where(Tramo.piso_id == piso.id, Tramo.codigo == codigo_tramo)
            )
            if tramo is None:
                omitidos.append(
                    f"{ruta.name}: el tramo {codigo_piso}-{codigo_tramo} no existe en el sistema"
                )
                continue

        if piso.plano_vigente(tramo) is not None:
            continue

        try:
            contenido = sanear_svg(ruta.read_bytes())
            ancho, alto = dimensiones_svg(contenido)
            plano = guardar_plano(
                sesion,
                piso,
                tramo,
                ruta.name,
                contenido,
                ancho_px=ancho,
                alto_px=alto,
                nombre=f"{codigo_edificio} {codigo_piso} · "
                + (f"Tramo {codigo_tramo[1:]}" if codigo_tramo else "Piso completo"),
            )
        except (PlanoRechazado, ValueError) as exc:
            omitidos.append(f"{ruta.name}: {exc}")
            continue
        cargados += 1
        print(f"  + {plano.nombre} ({ancho}×{alto}) ← {ruta.name}")

    return cargados, omitidos


def edificios_con_planos() -> list[str]:
    """Códigos de los edificios que tienen ``data/<código>/planos``."""
    return sorted(
        ruta.parent.name.upper()
        for ruta in DIR_DATA.glob("*/planos")
        if ruta.is_dir() and not ruta.parent.name.startswith("_")
    )


def main(argumentos: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Carga las láminas pendientes de los edificios")
    parser.add_argument(
        "edificios", nargs="*", help="Códigos de edificio (por omisión, todos los que tienen carpeta)"
    )
    parser.add_argument("--planos", type=Path, help="Carpeta de las láminas (con un solo edificio)")
    args = parser.parse_args(argumentos)
    edificios = [e.upper() for e in args.edificios] or edificios_con_planos()
    if args.planos and len(edificios) != 1:
        parser.error("--planos se usa con un solo edificio")

    for codigo in edificios:
        with SesionLocal() as sesion:
            cargados, omitidos = cargar(sesion, args.planos or dir_planos_de(codigo), codigo)
            sesion.commit()
        print(f"{codigo}: planos cargados: {cargados}" + ("" if cargados else " (todos estaban al día)"))
        if omitidos:
            print(f"  Láminas omitidas ({len(omitidos)}):")
            for motivo in omitidos:
                print(f"    - {motivo}")


if __name__ == "__main__":
    main()
