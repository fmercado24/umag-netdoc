"""Carga en bloque las fotografías del levantamiento de un edificio.

    python -m app.scripts.cargar_fotografias            # todos los edificios con fotos/
    python -m app.scripts.cargar_fotografias ING
    python -m app.scripts.cargar_fotografias ING --carpeta /media/usb/fotos-ing

Busca en ``data/<código en minúsculas>/fotos/`` archivos .jpg, .jpeg, .png o
.webp nombrados con el código del elemento (SOP §10.4):
``ING-SW01-P01-T2.jpg`` y, si hay más de una, ``ING-SW01-P01-T2_2.jpg``,
``ING-SW01-P01-T2_3.jpg``… El nombre del archivo queda como descripción de
la foto, así que correrlo de nuevo no la duplica: se puede ir sumando fotos
a la carpeta a medida que avanza el levantamiento.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import SesionLocal
from app.models import Edificio, Elemento
from app.scripts.importar_edificio import DIR_DATA, dir_datos_de
from app.servicios.fotografias import EXTENSIONES_FOTO, guardar_fotografia

#: "ING-SW01-P01-T2_2" → "ING-SW01-P01-T2"
RE_SECUENCIA = re.compile(r"_\d+$")


def cargar(sesion: Session, carpeta: Path, codigo_edificio: str) -> tuple[int, list[str]]:
    edificio = sesion.scalar(select(Edificio).where(Edificio.codigo == codigo_edificio.upper()))
    if edificio is None:
        raise SystemExit(f"No existe el edificio {codigo_edificio.upper()} en el catálogo")

    cargadas, omitidas = 0, []
    for ruta in sorted(carpeta.iterdir()):
        if not ruta.is_file() or ruta.suffix.lower() not in EXTENSIONES_FOTO:
            continue
        codigo = RE_SECUENCIA.sub("", ruta.stem).upper()
        elemento = sesion.scalar(
            select(Elemento).where(Elemento.codigo == codigo, Elemento.edificio_id == edificio.id)
        )
        if elemento is None:
            omitidas.append(f"{ruta.name}: no hay un elemento {codigo} en {edificio.codigo}")
            continue
        if any(f.descripcion == ruta.name for f in elemento.fotografias):
            continue  # ya cargada en una pasada anterior
        guardar_fotografia(sesion, elemento, ruta.name, ruta.read_bytes(), descripcion=ruta.name)
        cargadas += 1
    return cargadas, omitidas


def main(argumentos: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Carga las fotografías del levantamiento")
    parser.add_argument(
        "edificio", nargs="?", help="Código del edificio (por omisión, todos los que tienen fotos/)"
    )
    parser.add_argument(
        "--carpeta", type=Path, help="Carpeta de las fotos (por omisión data/<código>/fotos)"
    )
    args = parser.parse_args(argumentos)
    if args.carpeta and not args.edificio:
        parser.error("--carpeta se usa junto con el código del edificio")
    if args.edificio:
        destinos = [(args.edificio.upper(), args.carpeta or dir_datos_de(args.edificio) / "fotos")]
    else:
        destinos = [
            (carpeta.parent.name.upper(), carpeta)
            for carpeta in sorted(DIR_DATA.glob("*/fotos"))
            if carpeta.is_dir() and not carpeta.parent.name.startswith("_")
        ]
    if not destinos:
        print("No hay carpetas de fotos (data/<código>/fotos).")

    for codigo, carpeta in destinos:
        if not carpeta.is_dir():
            raise SystemExit(f"No existe la carpeta {carpeta}")
        with SesionLocal() as sesion:
            cargadas, omitidas = cargar(sesion, carpeta, codigo)
            sesion.commit()
        print(f"{codigo}: fotografías cargadas: {cargadas}")
        for motivo in omitidas:
            print(f"  - {motivo}")


if __name__ == "__main__":
    main()
