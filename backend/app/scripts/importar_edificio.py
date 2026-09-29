"""Importa el levantamiento de un edificio desde las planillas de la DSI.

    python -m app.scripts.importar_edificio CADI
    python -m app.scripts.importar_edificio ING --solo-advertencias
    python -m app.scripts.importar_edificio ING --agregar
    python -m app.scripts.importar_edificio ING --recargar

``--solo-advertencias`` simula la importación completa y descarta el
resultado: lista las discrepancias sin modificar la base, aunque el edificio
ya esté importado. ``--agregar`` suma lo nuevo (la planilla de un tramo que
se levantó después, más puntos de datos) sin tocar lo ya importado, sus
posiciones ni su historial. ``--recargar`` reemplaza lo importado antes (se
pierden posiciones e historial de esos elementos).

Fuentes, en ``data/<código en minúsculas>/`` (``<p>`` = código en minúsculas;
el procedimiento completo está en ``docs/guia-nuevo-edificio.md``):

* ``<p>-p<piso>-t<tramo>.csv`` (o ``<p>-p<piso>.csv`` si el piso no tiene
  tramos) — equipamiento. Son la fuente autoritativa: traen la **ubicación
  descriptiva** de cada elemento, que el SOP §9.1 exige.
* ``<p>-puntos-de-datos.csv`` — un punto de datos por fila (las planillas
  también los llaman "rosetas"), con el rótulo que codifica piso, tramo,
  rack y puerto, y el recinto donde está. Opcional.
* ``<p>-vlans.csv`` — leyenda de VLANs del edificio y la VLAN por omisión de
  cada servicio. Opcional.
* ``<p>-laminas.csv`` — elementos dibujados en la lámina de otro tramo que el
  de su rótulo. Opcional.
* ``<p>-global.csv`` — consolidado histórico. No se importa; se usa solo para
  contrastar y reportar diferencias. Opcional.

El importador **no completa lo que la planilla no dice**. Número de serie,
MAC, IP de gestión, categoría de cable, fechas y coordenadas quedan vacíos a
propósito: el reporte "Elementos incompletos por edificio" debe mostrar la
brecha real respecto de la sección 9 del SOP.
"""

from __future__ import annotations

import argparse
import csv
import io
import ipaddress
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import DIR_PROYECTO
from app.db.session import SesionLocal
from app.models import (
    Edificio,
    Elemento,
    Enlace,
    EstadoCondicion,
    EstadoOperativo,
    MedioEnlace,
    OrigenCambio,
    Piso,
    TipoElemento,
    Tramo,
    Vlan,
)
from app.servicios.codigos import construir_codigo
from app.servicios.historial import registrar_alta, registrar_cambios
from app.servicios.validacion import RE_MAC

DIR_DATA = DIR_PROYECTO / "data"


def dir_datos_de(codigo_edificio: str) -> Path:
    """Carpeta por omisión de las planillas: ``data/<código en minúsculas>``."""
    return DIR_DATA / codigo_edificio.lower()


def descubrir_planillas(
    dir_datos: Path, prefijo: str
) -> list[tuple[str, str, str | None]]:
    """Devuelve (archivo, piso, tramo) ordenado por piso y tramo.

    Las planillas de equipamiento se descubren por nombre de archivo:
    ``<prefijo>-p<piso>-t<tramo>.csv`` (el tramo es opcional). El piso y el
    tramo vienen del nombre y no de una columna, porque en estas planillas la
    columna "Ubicación" es la ubicación descriptiva del elemento. Basta con
    dejar un archivo nuevo —por ejemplo ``cadi-p02-t2.csv`` cuando se levante
    ese tramo— para que se importe.
    """
    patron = re.compile(rf"^{re.escape(prefijo)}-p(\d{{1,2}})(?:-t(\d+))?\.csv$", re.IGNORECASE)
    encontradas: list[tuple[int, int, str, str, str | None]] = []
    for ruta in dir_datos.glob("*.csv"):
        coincidencia = patron.match(ruta.name.lower())
        if not coincidencia:
            continue
        piso = int(coincidencia.group(1))
        tramo = int(coincidencia.group(2)) if coincidencia.group(2) else None
        encontradas.append(
            (piso, tramo or 0, ruta.name, f"P{piso:02d}", f"T{tramo}" if tramo else None)
        )
    return [(nombre, piso, tramo) for _, _, nombre, piso, tramo in sorted(encontradas)]

# Columnas de las planillas de equipamiento.
EQ_MODELO, EQ_ETIQUETA, EQ_TIPO, EQ_UBICACION = 0, 1, 2, 3
EQ_ESTADO_OP, EQ_ESTADO_COND, EQ_NOTAS, EQ_RACK = 4, 5, 6, 7

# Columnas de la planilla de puntos de datos.
PD_ROSETA, PD_ETIQUETA, PD_TIPO, PD_UBICACION = 0, 1, 2, 3
PD_ESTADO_OP, PD_ESTADO_COND, PD_NOTAS = 4, 5, 6

#: "Tipo" de la planilla → código del catálogo.
MAPA_TIPOS: dict[str, str] = {
    "patch panel": "PP",
    "patch panels": "PP",
    "access point": "AP",
    "access points": "AP",
    "cabecera f.o": "ODF",
    "central telefonica": "PBX",
    "rack": "R",
    "racks": "R",
    "router": "RT",
    "routers": "RT",
    "servidor": "SV",
    "servidores": "SV",
    "switch": "SW",
    "switches": "SW",
    "ups": "UPS",
    "puntos de datos (rosetas)": "PD",
    "punto de datos": "PD",
    "puntos de datos": "PD",
    # Sinónimos y los tipos que las planillas del CADI no usaron.
    "cabecera fo": "ODF",
    "cabeceras f.o": "ODF",
    "odf": "ODF",
    "distribuidor de fibra": "ODF",
    "pbx": "PBX",
    "media converter": "MC",
    "media converters": "MC",
    "conversor de medios": "MC",
    "convertidor de medios": "MC",
    "ont": "ONT",
    "onts": "ONT",
    "pdu": "PDU",
    "pdus": "PDU",
}

MARCAS: dict[str, str] = {
    "mikrotik": "MikroTik",
    "cisco": "Cisco",
    "huawei": "Huawei",
    "dell": "Dell",
    "hp ": "HP",
    "linksys": "Linksys",
    "tripp lite": "Tripp Lite",
    "d-link": "D-Link",
    "unifi": "Ubiquiti",
    "unfi": "Ubiquiti",
    "edgeswitch": "Ubiquiti",
    "grandstream": "Grandstream",
    "link made": "Link Made",
    "connection trimmerx": "Connection TrimmerX",
}

#: Prefijo del rótulo de un punto de datos → servicio que presta.
#: Solo se mapean los prefijos respaldados por la leyenda de VLANs y por los
#: rótulos de los switches (SW-COM / SW-TEL / SW CCTV). El resto se reporta.
SERVICIOS_POR_PREFIJO: dict[str, str] = {"D": "datos", "T": "telefonia", "C": "cctv"}

#: "Piso 1 - Tramo 2", o solo "Piso 1" en los edificios sin tramos.
RE_PISO_TRAMO = re.compile(r"piso\s*(\d+)(?:\s*-\s*tramo\s*(\d+))?", re.IGNORECASE)
RE_RACK = re.compile(r"rack\s*-?\s*(\d+)", re.IGNORECASE)
RE_PUNTOS = re.compile(r"(\d+)\s*puntos?", re.IGNORECASE)
RE_DISPONIBILIDAD = re.compile(r"disponibilidad\s*(\d+)\s*puntos?", re.IGNORECASE)
#: "P01-T2-R4-D01", o "P01-R4-D01" en los edificios sin tramos.
RE_ROTULO_PD = re.compile(r"^P0?(\d+)(?:-T(\d+))?-R0?(\d+)-(.+)$", re.IGNORECASE)
RE_SALA = re.compile(r"(\d{4}(?:[./]\d+)?)\s*$")

NOMBRES_PISO = {
    "P00": "Subterráneo",
    "P01": "Primer piso",
    "P02": "Segundo piso",
    "P03": "Tercer piso",
    "P04": "Cuarto piso",
    "P05": "Quinto piso",
    "P06": "Sexto piso",
}


def texto_csv(ruta: Path) -> tuple[str, str, str | None]:
    """Contenido, separador y, si hizo falta, un aviso sobre la codificación.

    Excel con la configuración regional de Chile guarda los CSV separados por
    punto y coma (la coma es el separador decimal), y el "CSV" a secas en
    Windows-1252 en vez de UTF-8. Se aceptan ambos para no depender de cómo
    se exportó la planilla.
    """
    contenido = ruta.read_bytes()
    aviso = None
    try:
        texto = contenido.decode("utf-8-sig")
    except UnicodeDecodeError:
        texto = contenido.decode("cp1252")
        aviso = (
            f"{ruta.name}: no está en UTF-8; se leyó como Windows-1252. Conviene guardarla "
            "como «CSV UTF-8» para no arriesgar tildes y eñes"
        )
    encabezado = texto.split("\n", 1)[0]
    separador = ";" if encabezado.count(";") > encabezado.count(",") else ","
    return texto, separador, aviso


def _leer_csv(ruta: Path) -> list[dict[str, str]]:
    """Filas no vacías de un CSV con encabezado, con las celdas sin espacios.

    Las celdas sobrantes (una coma sin comillas en un texto libre) se ignoran
    en vez de detener la importación.
    """
    if not ruta.exists():
        return []
    texto, separador, _ = texto_csv(ruta)
    filas = [
        {k.strip().lower(): (v or "").strip() for k, v in fila.items() if isinstance(k, str)}
        for fila in csv.DictReader(io.StringIO(texto, newline=""), delimiter=separador)
    ]
    return [fila for fila in filas if any(fila.values())]


#: Encabezado (sin tildes ni símbolos) → campo. Son columnas opcionales que
#: se agregan después de "Foto"; las planillas del CADI no las traían.
COLUMNAS_OPCIONALES = {
    "ip": "direccion_ip",
    "ip de gestion": "direccion_ip",
    "direccion ip": "direccion_ip",
    "mac": "direccion_mac",
    "direccion mac": "direccion_mac",
    "n de serie": "numero_serie",
    "no de serie": "numero_serie",
    "nro de serie": "numero_serie",
    "numero de serie": "numero_serie",
    "serie": "numero_serie",
}


def columnas_opcionales(encabezado: list[str]) -> dict[str, int]:
    """Posición de las columnas opcionales (IP, MAC, N° de serie) presentes."""
    encontradas: dict[str, int] = {}
    for indice, nombre in enumerate(encabezado):
        clave = re.sub(r"[^a-z ]", "", _sin_tildes(nombre.strip().lower())).strip()
        clave = re.sub(r"\s+", " ", clave)
        if clave in COLUMNAS_OPCIONALES:
            encontradas.setdefault(COLUMNAS_OPCIONALES[clave], indice)
    return encontradas


def _ubicacion(piso: str, tramo: str | None) -> str:
    return f"{piso}-{tramo}" if tramo else piso


def _codigo_piso(valor: str) -> str:
    """'1', 'P1' o 'P01' → 'P01'."""
    numero = re.sub(r"\D", "", valor)
    return f"P{int(numero):02d}" if numero else valor.upper()


def _codigo_tramo(valor: str) -> str | None:
    """'2', 'T2' o 'T02' → 'T2'; vacío → None."""
    numero = re.sub(r"\D", "", valor)
    return f"T{int(numero)}" if numero else None


class ReglasLamina:
    """Qué elementos están dibujados en la lámina de otro tramo que el de su
    rótulo (ver ``Elemento.tramo_lamina``), según ``<p>-laminas.csv``.

    Columnas: ``piso``, ``tramo``, ``recinto``, ``lamina`` y ``motivo``
    (libre). Una fila sin recinto vale para todo el tramo; una con recinto es
    una excepción que se busca en la ubicación y la etiqueta del elemento y
    tiene prioridad. En el CADI, lo rotulado P01-T3 está en la lámina T1
    salvo el auditorio, que sí está en la T3.
    """

    def __init__(self, filas: list[dict[str, str]]) -> None:
        self.por_tramo: dict[tuple[str, str], str] = {}
        self.por_recinto: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
        for fila in filas:
            clave = (_codigo_piso(fila.get("piso", "")), _codigo_tramo(fila.get("tramo", "")))
            lamina = _codigo_tramo(fila.get("lamina", ""))
            if not clave[1] or not lamina:
                continue
            recinto = fila.get("recinto", "").lower()
            if recinto:
                self.por_recinto[clave].append((recinto, lamina))
            else:
                self.por_tramo[clave] = lamina

    @classmethod
    def desde_csv(cls, ruta: Path) -> ReglasLamina:
        return cls(_leer_csv(ruta))

    def lamina(self, codigo_piso: str, codigo_tramo: str | None, texto: str) -> str | None:
        """Tramo de la lámina que dibuja el elemento, o None si es la de su tramo."""
        if not codigo_tramo:
            return None
        texto = texto.lower()
        for fragmento, lamina in self.por_recinto.get((codigo_piso, codigo_tramo), []):
            if fragmento in texto:
                return None if lamina == codigo_tramo else lamina
        return self.por_tramo.get((codigo_piso, codigo_tramo))


@dataclass
class Resultado:
    pisos: int = 0
    tramos: int = 0
    equipos: int = 0
    puntos: int = 0
    enlaces: int = 0
    vlans: int = 0
    racks_inferidos: list[str] = field(default_factory=list)
    advertencias: list[str] = field(default_factory=list)
    #: Modo --agregar: planillas de tramos ya importados, racks inferidos que
    #: la planilla completó y puntos de datos que ya existían.
    omitidas: list[str] = field(default_factory=list)
    racks_completados: list[str] = field(default_factory=list)
    puntos_existentes: int = 0


#: Observación de un rack que solo aparece en los rótulos. Si más tarde llega
#: su planilla (modo --agregar), se completa con ella.
OBSERVACION_RACK_INFERIDO = (
    "Rack referenciado por los rótulos del levantamiento pero sin ficha "
    "propia en las planillas. Requiere verificación en terreno."
)


# --------------------------------------------------------------------------
# Normalización
# --------------------------------------------------------------------------
def _sin_tildes(texto: str) -> str:
    return texto.translate(str.maketrans("áéíóúÁÉÍÓÚñÑ", "aeiouAEIOUnN"))


def normalizar_tipo(valor: str) -> str | None:
    clave = _sin_tildes(valor.strip().lower()).rstrip(":. ")
    return MAPA_TIPOS.get(clave)


def normalizar_estado(valor: str) -> EstadoOperativo:
    return (
        EstadoOperativo.INACTIVO
        if "fuera de servicio" in valor.lower()
        else EstadoOperativo.ACTIVO
    )


def normalizar_condicion(valor: str) -> EstadoCondicion | None:
    texto = valor.strip().lower()
    if texto.startswith("excelente"):
        return EstadoCondicion.EXCELENTE
    if texto.startswith("regular"):
        return EstadoCondicion.REGULAR
    if texto.startswith("malo"):
        return EstadoCondicion.MALO
    return None


def separar_marca_modelo(valor: str) -> tuple[str | None, str | None]:
    texto = valor.strip()
    if not texto:
        return None, None
    minuscula = texto.lower()
    marca = next((m for clave, m in MARCAS.items() if clave in minuscula), None)
    return marca, texto


def ficha_patch_panel(etiqueta: str, modelo: str, notas: str) -> dict:
    ficha: dict = {}

    coincidencia = RE_PUNTOS.search(etiqueta)
    total = int(coincidencia.group(1)) if coincidencia else None
    if total:
        ficha["puertos_totales"] = total

    texto_modelo = modelo.upper().replace(" ", "")
    if "CAT6A" in texto_modelo:
        ficha["categoria_cableado"] = "Cat6A"
    elif "CAT6" in texto_modelo:
        ficha["categoria_cableado"] = "Cat6"

    if total:
        disponibles = RE_DISPONIBILIDAD.search(notas)
        if disponibles:
            ficha["puertos_ocupados"] = max(total - int(disponibles.group(1)), 0)
        elif "ocupacion total" in _sin_tildes(notas).lower():
            ficha["puertos_ocupados"] = total

    return ficha


def interpretar_notas(notas: str) -> tuple[str | None, str | None]:
    """Separa la nota en (enlace, observación libre)."""
    texto = notas.strip()
    if not texto:
        return None, None
    if "Enlace:" in texto:
        izquierda, derecha = texto.split("Enlace:", 1)
        resto = izquierda.strip().strip(",;") or None
        return derecha.strip(), resto
    if texto.startswith(("F.O.", "F.O ", "F/UTP")):
        return texto, None
    return None, texto


def nombre_recinto(roseta: str) -> str:
    """'Roseta Oficina 1083' → 'Oficina 1083'."""
    texto = roseta.strip()
    return re.sub(r"^roseta\s+", "", texto, flags=re.IGNORECASE).strip() or texto


# --------------------------------------------------------------------------
# Territorio
# --------------------------------------------------------------------------
class Territorio:
    """Crea pisos y tramos bajo demanda y los mantiene en caché."""

    def __init__(self, sesion: Session, edificio: Edificio, resultado: Resultado) -> None:
        self.sesion = sesion
        self.edificio = edificio
        self.resultado = resultado
        self._pisos: dict[str, Piso] = {}
        self._tramos: dict[tuple[str, str], Tramo] = {}

    def piso(self, codigo: str) -> Piso:
        if codigo in self._pisos:
            return self._pisos[codigo]
        piso = self.sesion.scalar(
            select(Piso).where(Piso.edificio_id == self.edificio.id, Piso.codigo == codigo)
        )
        if piso is None:
            piso = Piso(
                edificio_id=self.edificio.id,
                codigo=codigo,
                nombre=NOMBRES_PISO.get(codigo),
                orden=int(codigo[1:]) if codigo[1:].isdigit() else 99,
            )
            self.sesion.add(piso)
            self.sesion.flush()
            self.resultado.pisos += 1
        self._pisos[codigo] = piso
        return piso

    def tramo(self, codigo_piso: str, codigo_tramo: str | None) -> Tramo | None:
        if not codigo_tramo:
            return None
        clave = (codigo_piso, codigo_tramo)
        if clave in self._tramos:
            return self._tramos[clave]
        piso = self.piso(codigo_piso)
        tramo = self.sesion.scalar(
            select(Tramo).where(Tramo.piso_id == piso.id, Tramo.codigo == codigo_tramo)
        )
        if tramo is None:
            tramo = Tramo(piso_id=piso.id, codigo=codigo_tramo, nombre=f"Tramo {codigo_tramo[1:]}")
            self.sesion.add(tramo)
            self.sesion.flush()
            self.resultado.tramos += 1
        self._tramos[clave] = tramo
        return tramo


# --------------------------------------------------------------------------
# Importador
# --------------------------------------------------------------------------
class Importador:
    def __init__(
        self, sesion: Session, dir_datos: Path, codigo_edificio: str, *, agregar: bool = False
    ) -> None:
        self.sesion = sesion
        self.dir_datos = dir_datos
        self.resultado = Resultado()

        codigo_edificio = codigo_edificio.upper()
        self.edificio = sesion.scalar(select(Edificio).where(Edificio.codigo == codigo_edificio))
        if self.edificio is None:
            raise SystemExit(
                f"No existe el edificio {codigo_edificio} en el catálogo. Revise el código "
                "(GET /api/v1/edificios) o agréguelo: ver docs/guia-nuevo-edificio.md"
            )
        prefijo = codigo_edificio.lower()
        self.prefijo = prefijo
        self.archivo_puntos = f"{prefijo}-puntos-de-datos.csv"
        self.archivo_vlans = f"{prefijo}-vlans.csv"
        self.archivo_global = f"{prefijo}-global.csv"
        self.reglas_lamina = ReglasLamina.desde_csv(dir_datos / f"{prefijo}-laminas.csv")
        #: servicio → número de VLAN, de la columna "servicio" de <p>-vlans.csv
        self.vlan_por_servicio: dict[str, int] = {}

        self.tipos = {t.codigo: t for t in sesion.scalars(select(TipoElemento)).all()}
        faltantes = set(MAPA_TIPOS.values()) - self.tipos.keys()
        if faltantes:
            raise SystemExit(
                f"Faltan tipos en el catálogo: {', '.join(sorted(faltantes))}. "
                "Ejecute antes: python -m app.scripts.cargar_catalogo"
            )

        self.territorio = Territorio(sesion, self.edificio, self.resultado)
        self.correlativos: dict[tuple[str, int], int] = defaultdict(int)
        self.racks: dict[int, Elemento] = {}  # número de rack → elemento
        self.codigos_usados: set[str] = set()
        #: Lo creado en esta pasada: las reglas de lámina se aplican solo a esto.
        self.creados: list[Elemento] = []
        self.agregar = agregar
        self.existentes: set[str] = set()
        self.tramos_importados: set[tuple[str, str | None]] = set()
        if agregar:
            self._cargar_existentes()

    def _cargar_existentes(self) -> None:
        """Modo --agregar: lo ya importado se conserva y se continúa desde ahí."""
        for elemento in self.sesion.scalars(
            select(Elemento).where(Elemento.edificio_id == self.edificio.id)
        ).unique():
            self.existentes.add(elemento.codigo)
            self.codigos_usados.add(elemento.codigo)
            tipo = elemento.tipo.codigo
            if elemento.correlativo is not None:
                clave = (tipo, elemento.piso_id)
                self.correlativos[clave] = max(self.correlativos[clave], elemento.correlativo)
            if tipo == "R" and elemento.correlativo is not None:
                self.racks[elemento.correlativo] = elemento
            # Un tramo cuenta como importado si tiene equipos de su planilla (un
            # rack inferido desde los rótulos no cuenta).
            if tipo != "PD" and elemento.observaciones != OBSERVACION_RACK_INFERIDO:
                self.tramos_importados.add((elemento.piso.codigo, elemento.tramo_codigo))

    # -- utilidades ------------------------------------------------------
    def _leer(self, nombre: str) -> list[list[str]]:
        ruta = self.dir_datos / nombre
        if not ruta.exists():
            self.resultado.advertencias.append(f"No se encontró la planilla {nombre}")
            return []
        texto, separador, aviso = texto_csv(ruta)
        if aviso:
            self.resultado.advertencias.append(aviso)
        filas = list(csv.reader(io.StringIO(texto, newline=""), delimiter=separador))
        self.encabezado = filas[0] if filas else []
        return [f for f in filas[1:] if any(c.strip() for c in f)]

    def _siguiente_correlativo(self, codigo_tipo: str, piso: Piso) -> int:
        clave = (codigo_tipo, piso.id)
        self.correlativos[clave] += 1
        return self.correlativos[clave]

    def _codigo_unico(self, codigo: str, contexto: str) -> str:
        if codigo not in self.codigos_usados:
            self.codigos_usados.add(codigo)
            return codigo
        for sufijo in range(2, 100):
            alterno = f"{codigo}-DUP{sufijo}"
            if alterno not in self.codigos_usados:
                self.codigos_usados.add(alterno)
                self.resultado.advertencias.append(
                    f"Rótulo duplicado en la planilla: '{codigo}' ({contexto}); "
                    f"se registró como '{alterno}'"
                )
                return alterno
        raise RuntimeError(f"Demasiados duplicados para {codigo}")

    def _crear(self, **campos) -> Elemento:
        elemento = Elemento(edificio_id=self.edificio.id, **campos)
        self.sesion.add(elemento)
        self.sesion.flush()
        registrar_alta(
            self.sesion,
            elemento,
            origen=OrigenCambio.IMPORTACION,
            usuario="importacion",
            comentario=f"Importado desde las planillas del levantamiento {self.edificio.codigo}",
        )
        self.creados.append(elemento)
        return elemento

    def _datos_opcionales(
        self, fila: list[str], opcionales: dict[str, int], archivo: str, referencia: str
    ) -> dict:
        """IP, MAC y número de serie, si la planilla trae esas columnas."""
        datos: dict = {}
        for campo, indice in opcionales.items():
            valor = fila[indice].strip() if len(fila) > indice else ""
            if not valor:
                continue
            if campo == "direccion_ip":
                try:
                    valor = str(ipaddress.ip_address(valor))
                except ValueError:
                    self.resultado.advertencias.append(
                        f"{archivo}: IP inválida '{valor}' en {referencia}; se omitió"
                    )
                    continue
            elif campo == "direccion_mac":
                if not RE_MAC.match(valor):
                    self.resultado.advertencias.append(
                        f"{archivo}: MAC inválida '{valor}' en {referencia}; se omitió"
                    )
                    continue
                valor = valor.upper().replace("-", ":")
            datos[campo] = valor
        return datos

    def _completar_rack(self, rack: Elemento, campo, archivo: str) -> None:
        """Un rack que solo se conocía por los rótulos recibe los datos de su
        planilla. Conserva su código, su posición y lo que tiene montado."""
        _, observacion = interpretar_notas(campo(EQ_NOTAS))
        registrar_cambios(
            self.sesion,
            rack,
            {
                "etiqueta": campo(EQ_ETIQUETA) or rack.etiqueta,
                "ubicacion_descriptiva": campo(EQ_UBICACION) or rack.ubicacion_descriptiva,
                "estado_operativo": normalizar_estado(campo(EQ_ESTADO_OP)),
                "estado_condicion": normalizar_condicion(campo(EQ_ESTADO_COND)),
                "observaciones": observacion or campo(EQ_MODELO) or None,
                "atributos": {**(rack.atributos or {}), "tipo_rack": "cerrado"},
            },
            origen=OrigenCambio.IMPORTACION,
            usuario="importacion",
            comentario=f"Ficha del rack completada con {archivo}",
        )
        self.resultado.racks_completados.append(rack.codigo)

    def _rack(self, numero: int, piso: Piso, tramo: Tramo | None) -> Elemento:
        """Devuelve el rack; lo crea como inferido si no está documentado."""
        if numero in self.racks:
            return self.racks[numero]

        codigo = self._codigo_unico(
            construir_codigo(
                edificio=self.edificio.codigo,
                tipo="R",
                correlativo=numero,
                piso=piso.codigo,
                tramo=tramo.codigo if tramo else None,
            ),
            f"rack {numero}",
        )
        elemento = self._crear(
            codigo=codigo,
            correlativo=numero,
            tipo_elemento_id=self.tipos["R"].id,
            piso_id=piso.id,
            tramo_id=tramo.id if tramo else None,
            etiqueta=f"Rack-{numero:02d}",
            estado_operativo=EstadoOperativo.ACTIVO,
            observaciones=OBSERVACION_RACK_INFERIDO,
            atributos={},
        )
        self.racks[numero] = elemento
        self.resultado.racks_inferidos.append(codigo)
        self.resultado.equipos += 1
        return elemento

    # -- VLANs -----------------------------------------------------------
    def importar_vlans(self) -> None:
        """Leyenda de ``<p>-vlans.csv``: numero, nombre, gateway, prefijo y
        servicio. El servicio (datos, telefonia, cctv) fija la VLAN por
        omisión de los puntos de datos cuyo rótulo lo indica."""
        for numero_fila, fila in enumerate(_leer_csv(self.dir_datos / self.archivo_vlans), 2):
            try:
                numero = int(fila.get("numero", ""))
            except ValueError:
                self.resultado.advertencias.append(
                    f"{self.archivo_vlans} fila {numero_fila}: número de VLAN ilegible "
                    f"'{fila.get('numero', '')}'"
                )
                continue
            servicio = fila.get("servicio", "").lower()
            if servicio:
                self.vlan_por_servicio[servicio] = numero
            existe = self.sesion.scalar(
                select(Vlan).where(Vlan.numero == numero, Vlan.edificio_id == self.edificio.id)
            )
            if existe:
                continue
            gateway = fila.get("gateway") or None
            prefijo = fila.get("prefijo", "")
            self.sesion.add(
                Vlan(
                    numero=numero,
                    nombre=fila.get("nombre") or f"VLAN {numero}",
                    gateway=gateway,
                    subred=f"{gateway}{prefijo}" if gateway and prefijo else None,
                    descripcion=f"Leyenda de {self.archivo_vlans}",
                    edificio_id=self.edificio.id,
                )
            )
            self.resultado.vlans += 1
        self.sesion.flush()

    # -- Equipamiento ----------------------------------------------------
    def importar_equipos(self) -> None:
        planillas = descubrir_planillas(self.dir_datos, self.prefijo)
        if not planillas:
            self.resultado.advertencias.append(
                f"No se encontró ninguna planilla de equipamiento en {self.dir_datos}"
            )
        # Dos pasadas por planilla: primero los racks (contenedores).
        for nombre, codigo_piso, codigo_tramo in planillas:
            if (codigo_piso, codigo_tramo) in self.tramos_importados:
                self.resultado.omitidas.append(f"{nombre} (ya importada)")
                continue
            filas = self._leer(nombre)
            if not filas:
                ubicacion = f"piso {codigo_piso}" + (f", tramo {codigo_tramo}" if codigo_tramo else "")
                self.resultado.advertencias.append(
                    f"{nombre}: planilla sin elementos levantados ({ubicacion})"
                )
                continue
            opcionales = columnas_opcionales(self.encabezado)
            for solo_racks in (True, False):
                for fila in filas:
                    self._fila_equipo(fila, codigo_piso, codigo_tramo, nombre, solo_racks, opcionales)

    def _fila_equipo(
        self,
        fila: list[str],
        codigo_piso: str,
        codigo_tramo: str | None,
        archivo: str,
        solo_racks: bool,
        opcionales: dict[str, int] | None = None,
    ) -> None:
        def campo(indice: int) -> str:
            return fila[indice].strip() if len(fila) > indice else ""

        codigo_tipo = normalizar_tipo(campo(EQ_TIPO))
        if codigo_tipo is None:
            if campo(EQ_TIPO):
                self.resultado.advertencias.append(
                    f"{archivo}: tipo no reconocido '{campo(EQ_TIPO)}'"
                )
            return
        if (codigo_tipo == "R") != solo_racks:
            return

        piso = self.territorio.piso(codigo_piso)
        tramo = self.territorio.tramo(codigo_piso, codigo_tramo)
        etiqueta_rack = campo(EQ_RACK)
        numero_rack = None
        if etiqueta_rack:
            coincidencia = RE_RACK.search(etiqueta_rack)
            if coincidencia:
                numero_rack = int(coincidencia.group(1))

        marca, modelo = separar_marca_modelo(campo(EQ_MODELO))
        enlace, observacion = interpretar_notas(campo(EQ_NOTAS))
        atributos: dict = {}

        if codigo_tipo == "R":
            if numero_rack is None:
                self.resultado.advertencias.append(
                    f"{archivo}: rack sin número identificable ('{campo(EQ_MODELO)}')"
                )
                return
            if numero_rack in self.racks:
                existente = self.racks[numero_rack]
                if self.agregar and existente.observaciones == OBSERVACION_RACK_INFERIDO:
                    self._completar_rack(existente, campo, archivo)
                    return
                self.resultado.advertencias.append(
                    f"{archivo}: el rack {numero_rack} aparece más de una vez"
                )
                return
            correlativo = numero_rack
            atributos = {"tipo_rack": "cerrado"}
            observacion = observacion or modelo
            marca, modelo = None, None
        else:
            correlativo = self._siguiente_correlativo(codigo_tipo, piso)
            if codigo_tipo == "PP":
                atributos = ficha_patch_panel(campo(EQ_ETIQUETA), campo(EQ_MODELO), campo(EQ_NOTAS))
                marca, modelo = None, None

        codigo = self._codigo_unico(
            construir_codigo(
                edificio=self.edificio.codigo,
                tipo=codigo_tipo,
                correlativo=correlativo,
                piso=piso.codigo,
                tramo=tramo.codigo if tramo else None,
            ),
            archivo,
        )

        padre = None
        if codigo_tipo != "R" and numero_rack is not None:
            padre = self._rack(numero_rack, piso, tramo)

        elemento = self._crear(
            codigo=codigo,
            correlativo=correlativo,
            tipo_elemento_id=self.tipos[codigo_tipo].id,
            piso_id=piso.id,
            tramo_id=tramo.id if tramo else None,
            padre_id=padre.id if padre else None,
            etiqueta=campo(EQ_ETIQUETA) or None,
            ubicacion_descriptiva=campo(EQ_UBICACION) or None,
            estado_operativo=normalizar_estado(campo(EQ_ESTADO_OP)),
            estado_condicion=normalizar_condicion(campo(EQ_ESTADO_COND)),
            marca=marca,
            modelo=modelo,
            observaciones=observacion,
            atributos=atributos,
            **self._datos_opcionales(fila, opcionales or {}, archivo, campo(EQ_ETIQUETA) or codigo),
        )
        self.resultado.equipos += 1

        if codigo_tipo == "R":
            self.racks[correlativo] = elemento

        if enlace:
            medio = MedioEnlace.FIBRA if enlace.upper().startswith("F.O") else MedioEnlace.COBRE
            self.sesion.add(
                Enlace(
                    origen_id=elemento.id,
                    destino_descripcion=enlace,
                    medio=medio,
                    etiqueta=enlace,
                    observaciones="Enlace transcrito del rótulo; falta vincular el destino",
                )
            )
            self.resultado.enlaces += 1

    # -- Puntos de datos --------------------------------------------------
    def importar_puntos_de_datos(self) -> None:
        if not (self.dir_datos / self.archivo_puntos).exists():
            return  # opcional: hay edificios sin puntos de datos levantados
        filas = self._leer(self.archivo_puntos)
        if not filas:
            return

        sin_etiqueta: dict[tuple[str, str], int] = defaultdict(int)
        prefijos_desconocidos: set[str] = set()

        for numero_fila, fila in enumerate(filas, start=2):

            def campo(indice: int) -> str:
                return fila[indice].strip() if len(fila) > indice else ""

            if normalizar_tipo(campo(PD_TIPO)) != "PD":
                self.resultado.advertencias.append(
                    f"{self.archivo_puntos} fila {numero_fila}: tipo no reconocido "
                    f"'{campo(PD_TIPO)}'"
                )
                continue

            coincidencia_ubicacion = RE_PISO_TRAMO.search(campo(PD_UBICACION))
            if not coincidencia_ubicacion:
                self.resultado.advertencias.append(
                    f"{self.archivo_puntos} fila {numero_fila}: ubicación ilegible "
                    f"'{campo(PD_UBICACION)}'"
                )
                continue
            codigo_piso = f"P{int(coincidencia_ubicacion.group(1)):02d}"
            tramo_ubicacion = coincidencia_ubicacion.group(2)
            codigo_tramo = f"T{int(tramo_ubicacion)}" if tramo_ubicacion else None

            rotulo = campo(PD_ETIQUETA)
            partes = RE_ROTULO_PD.match(rotulo)
            numero_rack: int | None = None
            puerto: str | None = None

            if partes:
                piso_rotulo = f"P{int(partes.group(1)):02d}"
                tramo_rotulo = f"T{int(partes.group(2))}" if partes.group(2) else None
                numero_rack = int(partes.group(3))
                puerto = partes.group(4).strip().upper()
                if (piso_rotulo, tramo_rotulo) != (codigo_piso, codigo_tramo):
                    self.resultado.advertencias.append(
                        f"{self.archivo_puntos} fila {numero_fila}: el rótulo '{rotulo}' indica "
                        f"{_ubicacion(piso_rotulo, tramo_rotulo)} pero la columna Ubicación dice "
                        f"{_ubicacion(codigo_piso, codigo_tramo)}; se usó el rótulo"
                    )
                    codigo_piso, codigo_tramo = piso_rotulo, tramo_rotulo
            elif rotulo and rotulo.lower() != "sin etiqueta":
                self.resultado.advertencias.append(
                    f"{self.archivo_puntos} fila {numero_fila}: rótulo '{rotulo}' no sigue el "
                    "patrón P<piso>-T<tramo>-R<rack>-<puerto> (o P<piso>-R<rack>-<puerto>)"
                )

            piso = self.territorio.piso(codigo_piso)
            tramo = self.territorio.tramo(codigo_piso, codigo_tramo)
            recinto = nombre_recinto(campo(PD_ROSETA))

            # --- Punto de datos (PD) -------------------------------------
            if puerto:
                detalle = f"R{numero_rack:02d}-{puerto}"
            else:
                sin_etiqueta[(codigo_piso, codigo_tramo)] += 1
                detalle = f"SIN-ROTULO-{sin_etiqueta[(codigo_piso, codigo_tramo)]:02d}"

            codigo_base = construir_codigo(
                edificio=self.edificio.codigo,
                tipo="PD",
                piso=piso.codigo,
                tramo=tramo.codigo if tramo else None,
                detalle=detalle,
            )
            if codigo_base in self.existentes:
                self.resultado.puntos_existentes += 1  # modo --agregar
                continue
            codigo_pd = self._codigo_unico(codigo_base, f"{recinto} (fila {numero_fila})")

            estado = normalizar_estado(campo(PD_ESTADO_OP))
            atributos: dict = {
                "estado_puerto": (
                    "habilitado" if estado is EstadoOperativo.ACTIVO else "deshabilitado"
                ),
            }
            if puerto:
                atributos["puerto_origen"] = rotulo.strip().upper()
                prefijo = puerto[0].upper()
                servicio = SERVICIOS_POR_PREFIJO.get(prefijo)
                if servicio:
                    atributos["servicio"] = servicio
                    if servicio in self.vlan_por_servicio:
                        atributos["vlan_por_defecto"] = self.vlan_por_servicio[servicio]
                else:
                    prefijos_desconocidos.add(puerto)

            punto = self._crear(
                codigo=codigo_pd,
                tipo_elemento_id=self.tipos["PD"].id,
                piso_id=piso.id,
                tramo_id=tramo.id if tramo else None,
                etiqueta=rotulo or None,
                ubicacion_descriptiva=recinto,
                estado_operativo=estado,
                estado_condicion=normalizar_condicion(campo(PD_ESTADO_COND)),
                observaciones=campo(PD_NOTAS) or None,
                atributos=atributos,
            )
            self.resultado.puntos += 1

            # Mapeo puerto del rack → punto de datos (SOP §9.2.3).
            if numero_rack is not None:
                rack = self._rack(numero_rack, piso, tramo)
                self.sesion.add(
                    Enlace(
                        origen_id=rack.id,
                        puerto_origen=puerto,
                        destino_id=punto.id,
                        medio=MedioEnlace.COBRE,
                        etiqueta=rotulo,
                        observaciones=(
                            "Mapeo transcrito del rótulo. Falta identificar el patch panel "
                            "específico dentro del rack."
                        ),
                    )
                )
                self.resultado.enlaces += 1

        if prefijos_desconocidos:
            ejemplos = ", ".join(sorted(prefijos_desconocidos)[:8])
            self.resultado.advertencias.append(
                f"Puertos con prefijo sin servicio asignado ({len(prefijos_desconocidos)}): "
                f"{ejemplos}. Solo se mapean D (datos), T (telefonía) y C (CCTV)."
            )
        self.sesion.flush()

    # -- Contraste con la planilla consolidada ---------------------------
    def contrastar_con_global(self) -> None:
        if not (self.dir_datos / self.archivo_global).exists():
            return  # opcional
        filas = self._leer(self.archivo_global)
        if not filas:
            return

        conteo_global: dict[tuple[str, str, str], int] = defaultdict(int)
        for fila in filas:
            codigo_tipo = normalizar_tipo(fila[1] if len(fila) > 1 else "")
            coincidencia = RE_PISO_TRAMO.search(fila[2] if len(fila) > 2 else "")
            if codigo_tipo is None or coincidencia is None:
                continue
            clave = (
                f"P{int(coincidencia.group(1)):02d}",
                f"T{int(coincidencia.group(2))}" if coincidencia.group(2) else "—",
                codigo_tipo,
            )
            conteo_global[clave] += 1

        conteo_actual: dict[tuple[str, str, str], int] = defaultdict(int)
        for elemento in self.sesion.scalars(
            select(Elemento).where(Elemento.edificio_id == self.edificio.id)
        ).unique():
            if elemento.tipo.codigo == "PD":
                continue
            clave = (
                elemento.piso.codigo,
                elemento.tramo.codigo if elemento.tramo else "—",
                elemento.tipo.codigo,
            )
            conteo_actual[clave] += 1

        for clave in sorted(set(conteo_global) | set(conteo_actual)):
            esperado = conteo_global.get(clave, 0)
            obtenido = conteo_actual.get(clave, 0)
            if esperado != obtenido:
                piso, tramo, tipo = clave
                self.resultado.advertencias.append(
                    f"Diferencia con la planilla consolidada en {piso}-{tramo} tipo {tipo}: "
                    f"consolidada {esperado}, planillas por tramo {obtenido}"
                )

    def asignar_laminas(self) -> None:
        """Aplica ``<p>-laminas.csv`` a lo que lleva marcador propio; lo
        montado sigue la lámina de su rack."""
        self.sesion.flush()
        # Solo lo creado en esta pasada: en modo --agregar no se pisan las
        # láminas que se hayan corregido a mano en el visor.
        for elemento in self.creados:
            if elemento.montado or elemento.tramo is None:
                continue
            texto = f"{elemento.ubicacion_descriptiva or ''} {elemento.etiqueta or ''}"
            lamina = self.reglas_lamina.lamina(elemento.piso.codigo, elemento.tramo.codigo, texto)
            if lamina:
                elemento.tramo_lamina = self.territorio.tramo(elemento.piso.codigo, lamina)

    def ejecutar(self) -> Resultado:
        self.importar_vlans()
        self.importar_equipos()
        self.importar_puntos_de_datos()
        self.asignar_laminas()
        self.contrastar_con_global()
        return self.resultado


def limpiar_edificio(sesion: Session, codigo_edificio: str) -> int:
    edificio = sesion.scalar(select(Edificio).where(Edificio.codigo == codigo_edificio.upper()))
    if edificio is None:
        return 0
    elementos = (
        sesion.scalars(select(Elemento).where(Elemento.edificio_id == edificio.id)).unique().all()
    )
    # Primero los contenidos, para no chocar con las claves foráneas.
    for elemento in sorted(elementos, key=lambda e: e.padre_id is None):
        sesion.delete(elemento)
    sesion.flush()
    return len(elementos)


def contar_elementos(sesion: Session, codigo_edificio: str) -> int:
    return sesion.scalar(
        select(func.count(Elemento.id))
        .join(Edificio, Elemento.edificio_id == Edificio.id)
        .where(Edificio.codigo == codigo_edificio.upper())
    ) or 0


def edificios_con_planillas() -> list[str]:
    """Códigos de las carpetas de ``data/`` que tienen planillas de equipamiento.

    Las carpetas que empiezan con "_" (como ``_plantilla``) no son edificios.
    """
    return sorted(
        carpeta.name.upper()
        for carpeta in DIR_DATA.iterdir()
        if carpeta.is_dir()
        and not carpeta.name.startswith("_")
        and descubrir_planillas(carpeta, carpeta.name.lower())
    )


def _informar(resultado: Resultado, completo: bool) -> None:
    if completo:
        print("Importación completada")
        print(f"  Pisos creados:        {resultado.pisos}")
        print(f"  Tramos creados:       {resultado.tramos}")
        print(f"  Equipos:              {resultado.equipos}")
        print(f"  Puntos de datos:      {resultado.puntos}")
        print(f"  Enlaces:              {resultado.enlaces}")
        print(f"  VLANs:                {resultado.vlans}")

    if resultado.omitidas:
        print(f"\nPlanillas omitidas ({len(resultado.omitidas)}): " + ", ".join(resultado.omitidas))
    if resultado.puntos_existentes:
        print(f"Puntos de datos que ya existían: {resultado.puntos_existentes}")
    if resultado.racks_completados:
        print("Racks completados con su planilla: " + ", ".join(resultado.racks_completados))

    if resultado.racks_inferidos:
        print(f"\nRacks inferidos, sin ficha en las planillas ({len(resultado.racks_inferidos)}):")
        for codigo in resultado.racks_inferidos:
            print(f"  - {codigo}")

    if resultado.advertencias:
        print(f"\nDiscrepancias detectadas ({len(resultado.advertencias)}):")
        for aviso in resultado.advertencias:
            print(f"  - {aviso}")


def importar_pendientes() -> None:
    """Importa los edificios con carpeta en ``data/`` que aún no tienen elementos.

    Es lo que corre ``iniciar.sh``: nunca reemplaza lo ya importado, y una
    carpeta con problemas se informa sin detener a las demás.
    """
    for codigo in edificios_con_planillas():
        with SesionLocal() as sesion:
            try:
                existentes = contar_elementos(sesion, codigo)
                if existentes:
                    print(f"{codigo}: ya tiene {existentes} elementos; no se reimporta.")
                    continue
                print(f"{codigo}: importando desde {dir_datos_de(codigo)}")
                resultado = Importador(sesion, dir_datos_de(codigo), codigo).ejecutar()
                sesion.commit()
            except SystemExit as exc:
                sesion.rollback()
                print(f"{codigo}: no se importó. {exc}")
                continue
        _informar(resultado, completo=True)


def main(argumentos: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Importa el levantamiento de un edificio desde sus planillas"
    )
    parser.add_argument(
        "edificio", nargs="?", help="Código del edificio en el catálogo, p. ej. CADI o ING"
    )
    parser.add_argument(
        "--pendientes",
        action="store_true",
        help="Importa todos los edificios con carpeta en data/ que aún no tienen elementos",
    )
    parser.add_argument(
        "--datos", type=Path, help="Carpeta de las planillas (por omisión data/<código>)"
    )
    modo = parser.add_mutually_exclusive_group()
    modo.add_argument(
        "--agregar",
        action="store_true",
        help="Suma lo nuevo (otro tramo, más puntos de datos) sin tocar lo ya importado",
    )
    modo.add_argument(
        "--recargar",
        action="store_true",
        help="Elimina los elementos existentes del edificio antes de importar",
    )
    parser.add_argument(
        "--solo-advertencias",
        action="store_true",
        help="Imprime únicamente el informe de discrepancias, sin modificar la base",
    )
    args = parser.parse_args(argumentos)
    if args.pendientes:
        importar_pendientes()
        return
    if not args.edificio:
        parser.error("indique el código del edificio (o --pendientes)")
    codigo = args.edificio.upper()
    dir_datos = args.datos or dir_datos_de(codigo)
    if not dir_datos.is_dir():
        raise SystemExit(f"No existe la carpeta de planillas {dir_datos}")

    with SesionLocal() as sesion:
        if args.solo_advertencias:
            # Se importa dentro de la transacción y se descarta todo: así el
            # informe es idéntico al de una carga real. Sin --agregar, sobre el
            # edificio vacío.
            if not args.agregar:
                limpiar_edificio(sesion, codigo)
            resultado = Importador(sesion, dir_datos, codigo, agregar=args.agregar).ejecutar()
            sesion.rollback()
        elif args.agregar:
            resultado = Importador(sesion, dir_datos, codigo, agregar=True).ejecutar()
            sesion.commit()
        else:
            existentes = contar_elementos(sesion, codigo)
            if existentes and not args.recargar:
                raise SystemExit(
                    f"{codigo} ya tiene {existentes} elementos importados.\n"
                    "  --agregar             suma lo nuevo sin tocar lo ya importado\n"
                    "  --recargar            los reemplaza (se pierden sus coordenadas sobre "
                    "el plano y su historial)\n"
                    "  --solo-advertencias   lista las discrepancias sin modificar la base"
                )
            if existentes:
                limpiar_edificio(sesion, codigo)
                print(f"Se eliminaron {existentes} elementos previos de {codigo}.\n")

            resultado = Importador(sesion, dir_datos, codigo).ejecutar()
            sesion.commit()

    _informar(resultado, completo=not args.solo_advertencias)


if __name__ == "__main__":
    main()
