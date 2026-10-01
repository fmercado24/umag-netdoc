"""Revisa y prepara las láminas SVG antes de cargarlas.

    python -m app.scripts.preparar_laminas ING              # solo informa
    python -m app.scripts.preparar_laminas ING --aplicar    # renombra, limpia y orienta
    python -m app.scripts.preparar_laminas --carpeta data/ing/planos --aplicar

Primero revisa el **nombre**: el cargador solo acepta la nomenclatura
``<edificio>-p<piso>[-t<tramo>].svg`` (ver ``app.servicios.planos``). Un nombre
del que se deduce el correcto («ing 1er piso tramo 2.svg» → ``ing-p01-t2.svg``)
se renombra; uno que no, se informa para renombrarlo a mano.

Las láminas que la DSI exporta desde PDF suelen traer además dos problemas
(así llegaron las del CADI):

1. **Caracteres de control** que XML no admite: el navegador descarta la
   lámina entera. Se eliminan.
2. **Dibujo girado** dentro de una hoja vertical: el texto se lee de arriba
   hacia abajo. Se detecta por la orientación de los textos y se gira la hoja
   para que quede horizontal y legible.

Con ``--aplicar`` el original de una lámina limpiada o girada queda en
``planos/originales/`` (el cargador de planos no mira esa carpeta) y la
versión preparada lo reemplaza. Correrlo dos veces no gira dos veces: el giro
ya aplicado se tiene en cuenta.
"""

from __future__ import annotations

import argparse
import math
import re
import shutil
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

from app.scripts.cargar_planos import archivos_de_laminas, dir_planos_de
from app.servicios.planos import (
    RE_CONTROL_XML,
    NombreLaminaInvalido,
    interpretar_nombre_lamina,
)

RE_RAIZ = re.compile(rb"<svg\b[^>]*>")
RE_TEXTO = re.compile(rb"<text\b[^>]*>")
RE_MATRIZ = re.compile(rb"matrix\(\s*([-\d.eE]+)[\s,]+([-\d.eE]+)")
RE_ROTAR = re.compile(rb"rotate\(\s*([-\d.eE]+)")
RE_ENVOLTORIO = re.compile(rb"\s*<g\b[^>]*\btransform=\"([^\"]*)\"")
RE_NUMEROS = re.compile(rb"[-\d.eE]+")

#: Giro del texto (grados, sentido horario como en SVG) → giro que lo endereza.
CORRECCION = {90: -90, -90: 90}


@dataclass
class Diagnostico:
    ancho: float
    alto: float
    caracteres_invalidos: int
    #: Cuántos textos hay en cada orientación neta (0, 90, 180, -90).
    orientaciones: Counter
    #: Giro que endereza el texto: -90 (antihorario), 90 (horario) o 0.
    giro: int

    @property
    def resumen(self) -> str:
        total = sum(self.orientaciones.values())
        dominante = self.orientaciones.most_common(1)[0] if total else (0, 0)
        orientacion = {0: "horizontal", 90: "girado a la derecha", -90: "girado a la izquierda",
                       180: "invertido"}[dominante[0]] if total else "sin textos"
        return (
            f"{self.ancho:g}×{self.alto:g}, texto {orientacion}"
            + (f" ({dominante[1]} de {total})" if total else "")
            + f", {self.caracteres_invalidos} caracteres inválidos"
        )


def _angulo_de(transformacion: bytes) -> int | None:
    """Giro de una transformación SVG, redondeado a múltiplos de 90°."""
    if matriz := RE_MATRIZ.search(transformacion):
        a, b = float(matriz.group(1)), float(matriz.group(2))
        angulo = math.degrees(math.atan2(b, a))
    elif rotacion := RE_ROTAR.search(transformacion):
        angulo = float(rotacion.group(1))
    else:
        return None
    angulo = int(round(angulo / 90) * 90) % 360
    return {0: 0, 90: 90, 180: 180, 270: -90}[angulo]


def _caja(raiz: bytes) -> tuple[float, float, float, float]:
    """(x, y, ancho, alto) del viewBox, o de width/height si no lo hay."""
    if caja := re.search(rb'viewBox="([^"]*)"', raiz):
        x, y, ancho, alto = (float(n) for n in RE_NUMEROS.findall(caja.group(1))[:4])
        return x, y, ancho, alto
    ancho = re.search(rb'\bwidth="([\d.]+)', raiz)
    alto = re.search(rb'\bheight="([\d.]+)', raiz)
    if not (ancho and alto):
        raise ValueError("el SVG no declara viewBox ni width/height")
    return 0.0, 0.0, float(ancho.group(1)), float(alto.group(1))


def diagnosticar(contenido: bytes) -> Diagnostico:
    raiz = RE_RAIZ.search(contenido)
    if raiz is None:
        raise ValueError("no es un SVG: falta la etiqueta <svg>")
    _, _, ancho, alto = _caja(raiz.group(0))

    # Un giro ya aplicado a todo el dibujo (el envoltorio que agrega este
    # script) se suma al de cada texto.
    base = 0
    if envoltorio := RE_ENVOLTORIO.match(contenido, raiz.end()):
        base = _angulo_de(envoltorio.group(1)) or 0

    orientaciones: Counter = Counter()
    for etiqueta in RE_TEXTO.findall(contenido):
        transformacion = re.search(rb'transform(?:="|:\s*)([^";]*)', etiqueta)
        angulo = _angulo_de(transformacion.group(1)) if transformacion else 0
        if angulo is None:
            angulo = 0
        neto = (angulo + base) % 360
        orientaciones[{0: 0, 90: 90, 180: 180, 270: -90}[neto]] += 1

    giro = 0
    total = sum(orientaciones.values())
    if total:
        dominante, cantidad = orientaciones.most_common(1)[0]
        # Solo se gira si la gran mayoría del texto está de lado.
        if dominante in CORRECCION and cantidad >= 0.6 * total:
            giro = CORRECCION[dominante]
    return Diagnostico(ancho, alto, len(RE_CONTROL_XML.findall(contenido)), orientaciones, giro)


def preparar(contenido: bytes) -> tuple[bytes, Diagnostico]:
    """Contenido limpio y, si hace falta, girado a horizontal."""
    diagnostico = diagnosticar(contenido)
    limpio = RE_CONTROL_XML.sub(b"", contenido)
    if diagnostico.giro:
        raiz = RE_RAIZ.search(limpio)
        x, y, ancho, alto = _caja(raiz.group(0))
        # rotate(-90) lleva (x, y) a (y, -x); rotate(90), a (-y, x). La nueva
        # caja es la imagen de la anterior: el dibujo no se mueve ni se recorta.
        if diagnostico.giro == -90:
            caja = (y, -(x + ancho), alto, ancho)
        else:
            caja = (-(y + alto), x, alto, ancho)
        nueva_raiz = raiz.group(0)
        for atributo in (rb"viewBox", rb"width", rb"height"):
            nueva_raiz = re.sub(rb"\s" + atributo + rb'="[^"]*"', b"", nueva_raiz)
        atributos = (
            f' viewBox="{caja[0]:g} {caja[1]:g} {caja[2]:g} {caja[3]:g}"'
            f' width="{alto:g}" height="{ancho:g}"'
        ).encode()
        nueva_raiz = nueva_raiz[:-1] + atributos + b">"
        envoltorio = f'\n<g transform="rotate({diagnostico.giro})">'.encode()
        cierre = limpio.rstrip()
        if not cierre.endswith(b"</svg>"):
            raise ValueError("el SVG no termina en </svg>")
        limpio = (
            limpio[: raiz.start()] + nueva_raiz + envoltorio
            + cierre[raiz.end() : -len(b"</svg>")] + b"</g>\n</svg>\n"
        )
    ElementTree.fromstring(limpio)  # debe quedar XML válido
    return limpio, diagnostico


def main(argumentos: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Revisa y prepara las láminas SVG")
    parser.add_argument("edificio", nargs="?", help="Código del edificio: usa data/<código>/planos")
    parser.add_argument("--carpeta", type=Path, help="Carpeta de las láminas, en vez del edificio")
    parser.add_argument(
        "--aplicar", action="store_true", help="Renombra, limpia y orienta (si no, solo informa)"
    )
    args = parser.parse_args(argumentos)
    if not args.edificio and not args.carpeta:
        parser.error("indique el código del edificio o --carpeta")
    carpeta = args.carpeta or dir_planos_de(args.edificio)
    edificio = args.edificio.upper() if args.edificio else None
    laminas = [r for r in archivos_de_laminas(carpeta) if r.suffix.lower() == ".svg"]
    if not laminas:
        raise SystemExit(f"No hay láminas .svg en {carpeta}")

    pendientes = a_mano = respaldadas = 0
    for ruta in laminas:
        nuevo_nombre = None
        try:
            interpretar_nombre_lamina(ruta.name, edificio=edificio)
        except NombreLaminaInvalido as exc:
            nuevo_nombre = exc.sugerencia
            if nuevo_nombre is None:
                a_mano += 1
                print(f"  ! {exc}: renómbrela a mano")
        try:
            contenido = ruta.read_bytes()
            preparado, diagnostico = preparar(contenido)
        except (ValueError, ElementTree.ParseError) as exc:
            print(f"  ! {ruta.name}: {exc}")
            continue
        acciones = []
        if diagnostico.caracteres_invalidos:
            acciones.append("limpiar")
        if diagnostico.giro:
            acciones.append("girar " + ("a la izquierda" if diagnostico.giro < 0 else "a la derecha"))
        cambia_contenido = bool(acciones)
        if nuevo_nombre:
            acciones.append(f"renombrar a «{nuevo_nombre}»")
        estado = ", ".join(acciones) if acciones else "lista"
        print(f"  {ruta.name}: {diagnostico.resumen} → {estado}")
        if not acciones:
            continue
        pendientes += 1
        if not args.aplicar:
            continue
        if cambia_contenido:
            respaldo = carpeta / "originales" / ruta.name
            respaldo.parent.mkdir(exist_ok=True)
            if not respaldo.exists():
                shutil.copy2(ruta, respaldo)
            ruta.write_bytes(preparado)
            respaldadas += 1
        if nuevo_nombre:
            destino = ruta.with_name(nuevo_nombre)
            if destino.exists():
                print(f"  ! no se renombra «{ruta.name}»: ya existe «{nuevo_nombre}»")
            else:
                ruta.rename(destino)
                # El rastro de descarga de Windows, si está, acompaña al archivo.
                rastro = ruta.with_name(ruta.name + ":Zone.Identifier")
                if rastro.exists():
                    rastro.rename(destino.with_name(destino.name + ":Zone.Identifier"))

    if a_mano:
        print(f"{a_mano} con un nombre que hay que corregir a mano (ver los avisos con !).")
    if not pendientes:
        if not a_mano:
            print("Todas las láminas están listas para cargarse.")
    elif args.aplicar:
        print(f"Preparadas {pendientes}.")
        if respaldadas:
            print(f"Los originales de las limpiadas o giradas quedaron en {carpeta / 'originales'}.")
    else:
        print(f"{pendientes} por preparar. Para hacerlo: --aplicar")

if __name__ == "__main__":
    main()
