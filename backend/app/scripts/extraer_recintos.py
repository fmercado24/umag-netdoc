"""Lee los recintos de las láminas y los deja en ``<código>-recintos.csv``.

    python -m app.scripts.extraer_recintos CADI
    python -m app.scripts.extraer_recintos CADI cadi-p01-t2.svg     # solo esa lámina

Cada sala de los planos lleva un código en su rótulo, escrito como lo hace
cada edificio: en el CADI, un número de cuatro cifras bajo el nombre que dice
el piso (``SALA 1`` / ``1083``); en la Biblioteca, la categoría, un número de
dos cifras que empieza de nuevo en cada piso y el nombre debajo (``E.`` /
``09`` / ``Oficina administrativa``). El OCR (``app.servicios.ocr_recintos``)
reconoce en cada lámina cómo rotula sus salas, y de lo leído quedan:

* los códigos de sala, con su nombre y el punto bajo el rótulo donde el
  sistema dibujará los elementos del recinto;
* los rótulos de los racks («RACK 08» → ``R08``), que ubican el rack aunque su
  sala no tenga número, como las salas eléctricas del CADI.

Un número tapado por una línea del dibujo (la X de un hall, una silla) no se
alcanza a leer en la lámina completa. Se vuelve a leer, solo y más grande,
bajo cada nombre que nombran las planillas y no apareció (y se acepta solo el
número que dice la planilla), y donde iría el código de cada nombre de sala
que quedó sin uno.

El resultado va a ``data/<código>/<código>-recintos.csv``: lámina, número,
nombre, x, y, y la huella de la versión de la lámina que se leyó. Se revisa y
se versiona como cualquier planilla: una fila mal leída se corrige o se borra
a mano. Al cargar las láminas, el sistema ubica cada elemento en el recinto
que dice su ubicación (ver ``app.servicios.recintos``). Si una lámina cambia,
hay que volver a leerla: el sistema no usa recintos de otra versión. Los
planos que se cargan desde el visor no necesitan esto: el sistema los lee solo
(``app.servicios.lectura_recintos``).

El informe final cruza lo leído con las planillas del levantamiento: los
recintos que las planillas nombran y que no aparecen en las láminas de su piso
son errores de transcripción o salas que el OCR no alcanzó a leer.

El OCR es una dependencia aparte, que solo necesita quien lee las láminas:

    .venv/bin/python -m pip install -r requirements-ocr.txt

Toma uno o dos minutos por lámina.
"""

from __future__ import annotations

import argparse
import csv
import io
import time
from collections import defaultdict
from pathlib import Path

from app.scripts.cargar_planos import archivos_de_laminas
from app.scripts.importar_edificio import (
    DIR_DATA,
    descubrir_planillas,
    nombre_recinto,
    texto_csv,
)
from app.servicios.planillas import (
    COLUMNAS_EQUIPO,
    COLUMNAS_PUNTOS,
    POSICIONES_EQUIPO,
    POSICIONES_PUNTOS,
    columnas_de,
    piso_y_tramo,
)
from app.servicios import ocr_recintos
from app.servicios.ocr_recintos import SinOcr, leer_recintos_de_lamina, parecido
from app.servicios.planos import (
    NombreLaminaInvalido,
    dimensiones_svg,
    interpretar_nombre_lamina,
    quitar_caracteres_de_control,
)
from app.servicios.recintos import (
    FilaRecinto,
    archivo_recintos,
    escribir_recintos,
    huella_lamina,
    leer_recintos,
    numero_base,
    numero_de_recinto,
)


def crear_ocr():
    try:
        return ocr_recintos.crear_ocr()
    except SinOcr as exc:
        raise SystemExit(str(exc)) from None


# --------------------------------------------------------------------------
# Planillas
# --------------------------------------------------------------------------
def recintos_de_las_planillas(dir_datos: Path, prefijo: str) -> dict[tuple[str, str], set[str]]:
    """(piso, número) → cómo nombran las planillas ese recinto."""
    nombres: dict[tuple[str, str], set[str]] = defaultdict(set)

    def filas(ruta: Path, campos: dict, posiciones: dict) -> list[dict[str, str]]:
        """Cada fila como {campo: valor}, con las columnas en cualquier orden."""
        if not ruta.is_file():
            return []
        texto, separador, _ = texto_csv(ruta)
        todas = list(csv.reader(io.StringIO(texto, newline=""), delimiter=separador))
        if not todas:
            return []
        indices = columnas_de(todas[0], campos, posiciones).indices
        return [
            {c: fila[i].strip() for c, i in indices.items() if len(fila) > i} for fila in todas[1:]
        ]

    for archivo, codigo_piso, _ in descubrir_planillas(dir_datos, prefijo):
        for fila in filas(dir_datos / archivo, COLUMNAS_EQUIPO, POSICIONES_EQUIPO):
            for texto in (fila.get("sala", ""), fila.get("ubicacion", "")):
                if numero := numero_de_recinto(texto, codigo_piso):
                    nombres[codigo_piso, numero].add(texto)
    for fila in filas(dir_datos / f"{prefijo}-puntos-de-datos.csv", COLUMNAS_PUNTOS, POSICIONES_PUNTOS):
        piso_tramo = piso_y_tramo(fila.get("ubicacion", ""))
        if piso_tramo is None:
            continue
        recinto = nombre_recinto(fila.get("roseta", ""))
        if numero := numero_de_recinto(recinto, piso_tramo[0]):
            nombres[piso_tramo[0], numero].add(recinto)
    return nombres


def _sugerencia(nombres: set[str], leidos: list[FilaRecinto]) -> str | None:
    """El recinto leído cuyo nombre se parece al de las planillas."""
    mejor = max(leidos, key=lambda f: parecido(f.nombre, nombres), default=None)
    if mejor is None or parecido(mejor.nombre, nombres) < 0.5:
        return None
    return f"{mejor.numero} ({mejor.nombre})"


# --------------------------------------------------------------------------
# Programa
# --------------------------------------------------------------------------
def main(argumentos: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Lee los números de recinto de las láminas")
    parser.add_argument("edificio", help="Código del edificio, p. ej. CADI")
    parser.add_argument(
        "laminas", nargs="*", help="Solo estas láminas (por omisión, todas las de la carpeta)"
    )
    parser.add_argument(
        "--datos", type=Path, help="Carpeta del edificio (por omisión data/<código>)"
    )
    args = parser.parse_args(argumentos)
    codigo = args.edificio.upper()
    dir_datos = args.datos or DIR_DATA / codigo.lower()
    dir_planos = dir_datos / "planos"

    pedidas = {n.lower() for n in args.laminas}
    laminas = []
    for ruta in archivos_de_laminas(dir_planos):
        if pedidas and ruta.name.lower() not in pedidas:
            continue
        try:
            lamina = interpretar_nombre_lamina(ruta.name, edificio=codigo)
        except NombreLaminaInvalido as exc:
            print(f"  ! {exc}")
            continue
        if lamina.extension == ".svg":
            laminas.append((ruta, lamina))
    if not laminas:
        raise SystemExit(f"No hay láminas SVG que leer en {dir_planos}")

    planillas = recintos_de_las_planillas(dir_datos, codigo.lower())
    ruta_csv = archivo_recintos(dir_datos, codigo)
    anteriores, avisos = leer_recintos(ruta_csv)
    for aviso in avisos:
        print(f"  ! {aviso}")
    leidas = {ruta.name for ruta, _ in laminas}
    filas = [f for f in anteriores if f.lamina not in leidas]

    ocr = crear_ocr()
    # Lo ya encontrado en cada piso: no se vuelve a buscar en sus otras láminas.
    del_piso: dict[str, set[str]] = defaultdict(set)
    for fila in filas:
        del_piso[interpretar_nombre_lamina(fila.lamina, edificio=codigo).piso].add(fila.numero)
    for ruta, lamina in laminas:
        inicio = time.monotonic()
        contenido = quitar_caracteres_de_control(ruta.read_bytes())
        ancho, alto = dimensiones_svg(contenido)
        esperados = {
            numero: nombres for (piso, numero), nombres in planillas.items() if piso == lamina.piso
        }
        lectura = leer_recintos_de_lamina(
            ruta, ancho, alto, lamina.piso, ocr, esperados=esperados, ya_en_el_piso=del_piso[lamina.piso]
        )
        huella = huella_lamina(contenido)
        for recinto in [*lectura.recintos, *lectura.racks]:
            filas.append(FilaRecinto(ruta.name, recinto.numero, recinto.nombre, recinto.x, recinto.y, huella))
            del_piso[lamina.piso].add(recinto.numero)
        print(
            f"  {ruta.name}: {len(lectura.recintos)} recintos"
            + (f" ({lectura.releidos} en la segunda lectura)" if lectura.releidos else "")
            + (f", racks {', '.join(r.numero for r in lectura.racks)}" if lectura.racks else "")
            + f" ({time.monotonic() - inicio:.0f} s)"
            + (f"\n    · rotulado: {lectura.rotulado.describir()}" if lectura.rotulado else ""),
            flush=True,
        )
        for aviso in lectura.avisos:
            print(f"    · {aviso}")

    escribir_recintos(ruta_csv, filas)
    print(f"\nRecintos guardados en {ruta_csv}")

    # Lo que las planillas nombran y no aparece en las láminas de su piso.
    por_piso: dict[str, list[FilaRecinto]] = defaultdict(list)
    for fila in filas:
        por_piso[interpretar_nombre_lamina(fila.lamina, edificio=codigo).piso].append(fila)
    faltan = []
    for (piso, numero), nombres in sorted(planillas.items()):
        leidos = por_piso.get(piso)
        if not leidos:
            continue  # piso sin láminas leídas
        if {numero, numero_base(numero)} & {f.numero for f in leidos}:
            continue
        sugerencia = _sugerencia(nombres, leidos)
        faltan.append(
            f"    - {piso} {numero} «{' / '.join(sorted(nombres))}»"
            + (f" → en la lámina: {sugerencia}" if sugerencia else "")
        )
    if faltan:
        print(
            f"\nRecintos de las planillas que no aparecen en las láminas de su piso ({len(faltan)}).\n"
            "  Puede ser un número mal transcrito en la planilla o un rótulo que el OCR no leyó\n"
            f"  (agréguelo a mano a {ruta_csv.name}):"
        )
        print("\n".join(faltan))


if __name__ == "__main__":
    main()
