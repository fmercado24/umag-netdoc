"""Carga las láminas nuevas o modificadas de los edificios.

    python -m app.scripts.cargar_planos              # todos los edificios con carpeta
    python -m app.scripts.cargar_planos ING CADI     # solo esos
    python -m app.scripts.cargar_planos ING --planos /otra/carpeta

Las láminas se buscan en ``data/<código en minúsculas>/planos`` y su nombre
dice dónde van, con la nomenclatura obligatoria de las planillas:
``ing-p01-t2.svg`` (tramo T2 del piso P01), ``ing-p04.svg`` (piso P04
completo), ``ing-p00.svg`` (subterráneo). Un archivo que no la sigue, que es
de otro edificio o que no es SVG se informa y no se carga; si el nombre se
deja deducir («ing 1er piso tramo 2.svg»), el aviso trae el nombre correcto,
y ``app.scripts.preparar_laminas ING --aplicar`` renombra esos archivos.

Se compara el contenido de cada lámina con las versiones ya registradas de su
piso–tramo, así que el script puede correrse cada vez que se inicia el sistema:

* sin plano vigente, la lámina se carga;
* igual a la vigente, o a una anterior, no se toca. Esto último protege una
  versión subida después desde el visor o la API;
* distinta de todas, se carga como versión nueva y la anterior queda como
  histórica. Los elementos ubicados sobre ella pasan a la nueva si la lámina
  conserva su tamaño. Si el tamaño cambió, quedan sin ubicar (las coordenadas
  anteriores quedan en su historial) y el script los lista para volver a
  marcarlos en el visor.

Luego se cargan los recintos de ``<código>-recintos.csv`` (los números de
sala que ``app.scripts.extraer_recintos`` leyó de cada lámina) y cada elemento
que aún no está en el plano se ubica en su recinto: el número de sala que trae
su ubicación (ver ``app.servicios.recintos``). Lo que ya tiene posición no se
toca, y lo que no se pudo ubicar se lista.

Después se generan las teselas de cada plano vigente que aún no las tiene
(ver ``app.servicios.teselas``): es lo que el visor muestra para moverse con
fluidez. Toma unos segundos por lámina y se hace una sola vez por versión.

Las dimensiones del plano se toman del propio SVG. Antes de cargar las láminas
conviene pasarlas por ``app.scripts.preparar_laminas`` (limpieza y
orientación).
"""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import configuracion
from app.db.session import SesionLocal
from app.models import Edificio, OrigenCambio, Piso, Plano, Tramo
from app.scripts.importar_edificio import DIR_DATA, ubicar_en_recintos
from app.servicios.planos import (
    NombreLaminaInvalido,
    PlanoRechazado,
    dimensiones_svg,
    guardar_plano,
    interpretar_nombre_lamina,
    quitar_caracteres_de_control,
    sanear_svg,
    trasladar_posiciones,
)
from app.servicios.teselas import asegurar_teselas, leer_teselas


def dir_planos_de(codigo_edificio: str) -> Path:
    return DIR_DATA / codigo_edificio.lower() / "planos"


def archivos_de_laminas(carpeta: Path) -> list[Path]:
    """Los archivos de la carpeta de láminas, sin subcarpetas (``originales/``),
    ocultos ni los ``:Zone.Identifier`` que deja Windows al descargar."""
    if not carpeta.is_dir():
        return []
    return sorted(
        ruta
        for ruta in carpeta.iterdir()
        if ruta.is_file()
        and not ruta.name.startswith(".")
        and not ruta.name.endswith(":Zone.Identifier")
    )


@dataclass
class Resultado:
    nuevos: int = 0
    actualizados: int = 0
    omitidos: list[str] = field(default_factory=list)
    #: Omitidas por un nombre fuera de la nomenclatura que se deja corregir.
    renombrables: int = 0
    #: Códigos de los elementos que quedaron sin ubicar, por lámina.
    sin_ubicar: dict[str, list[str]] = field(default_factory=dict)


def _ya_registrada(contenido: bytes, versiones: list[Plano]) -> bool:
    """Si la lámina es idéntica a alguna versión guardada (la vigente primero)."""
    for plano in sorted(versiones, key=lambda p: not p.vigente):
        guardado = configuracion.dir_media / plano.archivo
        # El tamaño descarta casi siempre sin leer archivos de decenas de MB.
        if (
            guardado.is_file()
            and guardado.stat().st_size == len(contenido)
            and guardado.read_bytes() == contenido
        ):
            return True
    return False


def cargar(sesion: Session, dir_planos: Path, codigo_edificio: str) -> Resultado:
    codigo_edificio = codigo_edificio.upper()
    edificio = sesion.scalar(select(Edificio).where(Edificio.codigo == codigo_edificio))
    if edificio is None:
        raise SystemExit(
            f"No existe el edificio {codigo_edificio} en el catálogo "
            "(ver docs/guia-nuevo-edificio.md)"
        )

    resultado = Resultado()
    vistas: dict[tuple[str, str | None], str] = {}
    for ruta in archivos_de_laminas(dir_planos):
        try:
            lamina = interpretar_nombre_lamina(ruta.name, edificio=codigo_edificio)
        except NombreLaminaInvalido as exc:
            resultado.omitidos.append(str(exc))
            resultado.renombrables += exc.sugerencia is not None
            continue
        if lamina.extension != ".svg":
            resultado.omitidos.append(
                f"«{ruta.name}»: desde la carpeta solo se cargan láminas SVG (guía, sección 4)"
            )
            continue
        codigo_piso, codigo_tramo = lamina.piso, lamina.tramo
        if (anterior := vistas.get((codigo_piso, codigo_tramo))) is not None:
            resultado.omitidos.append(
                f"«{ruta.name}»: {lamina.ubicacion} ya tiene la lámina «{anterior}»"
            )
            continue
        vistas[codigo_piso, codigo_tramo] = ruta.name

        piso = sesion.scalar(
            select(Piso).where(Piso.edificio_id == edificio.id, Piso.codigo == codigo_piso)
        )
        if piso is None:
            resultado.omitidos.append(
                f"«{ruta.name}»: el piso {codigo_piso} no existe en el sistema"
            )
            continue
        tramo = None
        if codigo_tramo:
            tramo = sesion.scalar(
                select(Tramo).where(Tramo.piso_id == piso.id, Tramo.codigo == codigo_tramo)
            )
            if tramo is None:
                resultado.omitidos.append(
                    f"«{ruta.name}»: el tramo {codigo_piso}-{codigo_tramo} no existe en el sistema"
                )
                continue

        sesion.refresh(piso, ["planos"])
        tramo_id = tramo.id if tramo else None
        versiones = [p for p in piso.planos if p.tramo_id == tramo_id]
        contenido = ruta.read_bytes()
        if versiones and _ya_registrada(quitar_caracteres_de_control(contenido), versiones):
            continue

        try:
            contenido = sanear_svg(contenido)
            ancho, alto = dimensiones_svg(contenido)
            plano = guardar_plano(
                sesion, piso, tramo, ruta.name, contenido, ancho_px=ancho, alto_px=alto
            )
        except (PlanoRechazado, ValueError) as exc:
            resultado.omitidos.append(f"«{ruta.name}»: {exc}")
            continue

        if versiones:
            resultado.actualizados += 1
            print(f"  ↻ {plano.nombre}: versión nueva ({ancho}×{alto}) ← {ruta.name}")
            sin_ubicar = trasladar_posiciones(sesion, plano, origen=OrigenCambio.SISTEMA)
            if sin_ubicar:
                resultado.sin_ubicar[plano.nombre] = [e.codigo for e in sin_ubicar]
        else:
            resultado.nuevos += 1
            print(f"  + {plano.nombre} ({ancho}×{alto}) ← {ruta.name}")

    return resultado


def generar_teselas_pendientes(codigo_edificio: str) -> None:
    """Teselas de los planos vigentes del edificio que todavía no las tienen.

    Va aparte de ``cargar`` y después de confirmar sus cambios: dibujar una
    lámina toma segundos, y la base no debe quedar retenida mientras tanto.
    """
    with SesionLocal() as sesion:
        planos = sesion.scalars(
            select(Plano)
            .join(Piso, Plano.piso_id == Piso.id)
            .join(Edificio, Piso.edificio_id == Edificio.id)
            .where(Edificio.codigo == codigo_edificio.upper(), Plano.vigente.is_(True))
            .order_by(Plano.nombre)
        )
        pendientes = [
            (p.nombre, p.archivo, p.ancho_px) for p in planos if not leer_teselas(p.archivo)
        ]
    if not pendientes:
        return
    print(f"  Generando teselas de {len(pendientes)} lámina(s), unos segundos c/u…", flush=True)
    for nombre, archivo, ancho_px in pendientes:
        inicio = time.monotonic()
        if asegurar_teselas(archivo, ancho_px):
            print(f"    ▦ {nombre} ({time.monotonic() - inicio:.0f} s)", flush=True)
        else:
            print(f"    ! {nombre}: sin teselas, el visor mostrará la lámina original", flush=True)


def edificios_con_planos() -> list[str]:
    """Códigos de los edificios que tienen ``data/<código>/planos``."""
    return sorted(
        ruta.parent.name.upper()
        for ruta in DIR_DATA.glob("*/planos")
        if ruta.is_dir() and not ruta.parent.name.startswith("_")
    )


def main(argumentos: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Carga las láminas nuevas o modificadas")
    parser.add_argument(
        "edificios", nargs="*", help="Códigos de edificio (por omisión, todos los que tienen carpeta)"
    )
    parser.add_argument("--planos", type=Path, help="Carpeta de las láminas (con un solo edificio)")
    args = parser.parse_args(argumentos)
    edificios = [e.upper() for e in args.edificios] or edificios_con_planos()
    if args.planos and len(edificios) != 1:
        parser.error("--planos se usa con un solo edificio")

    for codigo in edificios:
        dir_planos = args.planos or dir_planos_de(codigo)
        with SesionLocal() as sesion:
            resultado = cargar(sesion, dir_planos, codigo)
            sesion.commit()
        if resultado.nuevos or resultado.actualizados:
            print(
                f"{codigo}: láminas nuevas: {resultado.nuevos}, "
                f"versiones nuevas: {resultado.actualizados}"
            )
        else:
            print(f"{codigo}: las láminas están al día")
        for lamina, codigos in resultado.sin_ubicar.items():
            cuantos = (
                "1 elemento quedó sin ubicar"
                if len(codigos) == 1
                else f"{len(codigos)} elementos quedaron sin ubicar"
            )
            print(f"  {lamina} cambió de tamaño: {cuantos} (volver a marcarlos en el visor):")
            for codigo_elemento in codigos:
                print(f"    - {codigo_elemento}")
        if resultado.omitidos:
            print(f"  Láminas omitidas ({len(resultado.omitidos)}):")
            for motivo in resultado.omitidos:
                print(f"    - {motivo}")
        if resultado.renombrables:
            print(
                "  Para renombrarlas a la nomenclatura: "
                f"python -m app.scripts.preparar_laminas {codigo} --aplicar"
            )
        # <código>-recintos.csv va junto a las planillas, en la carpeta que
        # contiene la de las láminas.
        ubicar_en_recintos(codigo, dir_planos.parent)
        generar_teselas_pendientes(codigo)


if __name__ == "__main__":
    main()
