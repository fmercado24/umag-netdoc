"""Cómo se leen las planillas del levantamiento, aunque traigan errores de tipeo.

Las planillas las llena una persona en Excel, en terreno: «Swich», «Acces
Point», «Operatibo», «Rak 4» o una columna escrita sin tilde no deben perder la
fila. Cada valor se reconoce primero tal cual, sin mayúsculas ni tildes; si no,
por su parecido con los valores admitidos (``difflib``, el mismo criterio que
usa la búsqueda de salas). Lo que se corrigió se informa, para que la
planilla de origen se arregle (SOP §10.6), y lo que no se reconoce no se
inventa: se informa y queda vacío, o la fila no se importa si sin ese dato no
se sabe qué es.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from difflib import get_close_matches

from app.models import EstadoCondicion, EstadoOperativo

#: Qué tan parecido debe ser un valor mal escrito al admitido (0 a 1).
CORTE_PARECIDO = 0.8


def normalizar(texto: str | None) -> str:
    """Minúsculas, sin tildes ni símbolos raros y con un espacio entre palabras."""
    base = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", base).strip()


def _parecido(texto: str, opciones: list[str]) -> str | None:
    encontradas = get_close_matches(texto, opciones, n=1, cutoff=CORTE_PARECIDO)
    return encontradas[0] if encontradas else None


@dataclass
class Lectura:
    """Lo que se entendió de un valor de la planilla.

    ``corregido`` dice cómo se leyó un valor mal escrito («swich» → «switch»);
    ``reconocido`` es falso si no se entendió.
    """

    valor: object = None
    reconocido: bool = True
    corregido: str | None = None


# --------------------------------------------------------------------------
# Tipo de elemento
# --------------------------------------------------------------------------
#: «Tipo» de la planilla, ya normalizado → código del catálogo.
MAPA_TIPOS: dict[str, str] = {
    "patch panel": "PP",
    "patch panels": "PP",
    "patchpanel": "PP",
    "access point": "AP",
    "access points": "AP",
    "punto de acceso": "AP",
    "puntos de acceso": "AP",
    "cabecera f.o": "ODF",
    "cabecera fo": "ODF",
    "cabeceras f.o": "ODF",
    "cabecera de fibra": "ODF",
    "cabecera fibra optica": "ODF",
    "odf": "ODF",
    "distribuidor de fibra": "ODF",
    "distribuidor de fibra optica": "ODF",
    "central telefonica": "PBX",
    "pbx": "PBX",
    "rack": "R",
    "racks": "R",
    "gabinete": "R",
    "gabinetes": "R",
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
    "roseta": "PD",
    "rosetas": "PD",
    "media converter": "MC",
    "media converters": "MC",
    "conversor de medio": "MC",
    "conversor de medios": "MC",
    "convertidor de medios": "MC",
    "ont": "ONT",
    "onts": "ONT",
    "terminal de red optica": "ONT",
    "pdu": "PDU",
    "pdus": "PDU",
}
#: El código del catálogo también vale como tipo: «SW», «AP», «R».
CODIGOS_TIPO = sorted(set(MAPA_TIPOS.values()))


def leer_tipo(texto: str) -> Lectura:
    clave = normalizar(texto).rstrip(":. ")
    if not clave:
        return Lectura(reconocido=False)
    if clave in MAPA_TIPOS:
        return Lectura(MAPA_TIPOS[clave])
    if clave.upper() in CODIGOS_TIPO:
        return Lectura(clave.upper())
    if parecida := _parecido(clave, list(MAPA_TIPOS)):
        return Lectura(MAPA_TIPOS[parecida], corregido=parecida)
    return Lectura(reconocido=False)


# --------------------------------------------------------------------------
# Estado operativo y de condición
# --------------------------------------------------------------------------
#: En orden: «no operativo» e «inactivo» se revisan antes que «operativo» y «activo».
ESTADOS: list[tuple[EstadoOperativo, tuple[str, ...]]] = [
    (EstadoOperativo.EN_MANTENIMIENTO, ("en mantencion", "mantencion", "en mantenimiento", "mantenimiento")),
    (EstadoOperativo.EN_FALLA, ("en falla", "con falla", "falla", "caido", "no responde")),
    (
        EstadoOperativo.INACTIVO,
        (
            "fuera de servicio", "no operativo", "inactivo", "apagado", "desconectado",
            "sin uso", "sin servicio", "dado de baja", "offline",
        ),
    ),
    (
        EstadoOperativo.ACTIVO,
        ("operativo", "activo", "en linea", "online", "funcionando", "en uso", "habilitado", "ok"),
    ),
]
CONDICIONES: list[tuple[EstadoCondicion, tuple[str, ...]]] = [
    (EstadoCondicion.MALO, ("malo", "mala", "deficiente", "danado", "danada", "deteriorado", "roto")),
    (EstadoCondicion.OBSOLETO, ("obsoleto", "obsoleta")),
    (EstadoCondicion.REGULAR, ("regular", "aceptable")),
    (EstadoCondicion.EXCELENTE, ("excelente", "bueno", "buena", "optimo", "optima", "nuevo", "nueva")),
]


def _leer_por_frases(texto: str, grupos: list[tuple[object, tuple[str, ...]]]) -> Lectura:
    clave = normalizar(texto)
    if not clave:
        return Lectura(reconocido=False)
    for valor, frases in grupos:
        if any(re.search(rf"\b{re.escape(f)}\b", clave) for f in frases):
            return Lectura(valor)
    # Mal escrito: la frase entera («fuera de serbicio») o una de sus palabras («operatibo»).
    todas = {f: valor for valor, frases in grupos for f in frases}
    candidatos = [clave, *re.findall(r"[a-z]+", clave)]
    for candidato in candidatos:
        if len(candidato) >= 4 and (parecida := _parecido(candidato, list(todas))):
            return Lectura(todas[parecida], corregido=parecida)
    return Lectura(reconocido=False)


def leer_estado(texto: str) -> Lectura:
    """El estado operativo. Vacío es «activo», como en el alta desde el visor."""
    if not normalizar(texto):
        return Lectura(EstadoOperativo.ACTIVO)
    return _leer_por_frases(texto, ESTADOS)


def leer_condicion(texto: str) -> Lectura:
    """El estado de condición física; vacío queda vacío (es un atributo que falta)."""
    if not normalizar(texto):
        return Lectura(None)
    return _leer_por_frases(texto, CONDICIONES)


# --------------------------------------------------------------------------
# Rack, piso y tramo
# --------------------------------------------------------------------------
#: «Rack-04», «RACK 4», «Rack N° 4», «R04», «Rak 4», «Gabinete 2».
RE_RACK = re.compile(
    r"\b(?:rack|rak|rac|rck|gabinete|r)\s*[-#.:]*\s*(?:n(?:ro|um|umero|o)?\s*[.:]?\s*)?0*(\d{1,3})\b"
)


def numero_de_rack(texto: str | None) -> int | None:
    coincidencia = RE_RACK.search(normalizar(texto))
    return int(coincidencia.group(1)) if coincidencia else None


#: «Piso 1», «P01», «Pizo 1»; «Tramo 2», «T2».
RE_PISO = re.compile(r"\b(?:piso|pizo|pis|p)\s*[-.:]?\s*0*(\d{1,2})\b")
RE_TRAMO = re.compile(r"\b(?:tramo|tamo|trmo|t)\s*[-.:]?\s*0*(\d{1,2})\b")
RE_SUBTERRANEO = re.compile(r"subterr|sotano|subsuelo|\bsub\b")


def piso_y_tramo(texto: str | None) -> tuple[str, str | None] | None:
    """«Piso 1 - Tramo 2» o «P01-T2» → ('P01', 'T2'); «Subterráneo» → ('P00', None).

    None si el texto no dice el piso.
    """
    clave = normalizar(texto)
    tramo = RE_TRAMO.search(clave)
    codigo_tramo = f"T{int(tramo.group(1))}" if tramo else None
    if piso := RE_PISO.search(clave):
        return f"P{int(piso.group(1)):02d}", codigo_tramo
    if RE_SUBTERRANEO.search(clave):
        return "P00", codigo_tramo
    return None


# --------------------------------------------------------------------------
# Columnas
# --------------------------------------------------------------------------
#: Columnas de las planillas de equipamiento: campo → nombres admitidos.
COLUMNAS_EQUIPO: dict[str, tuple[str, ...]] = {
    "modelo": ("elemento", "modelo", "marca y modelo", "marca modelo", "equipo", "descripcion", "dispositivo"),
    "etiqueta": ("etiqueta", "rotulo", "rotulo fisico"),
    "tipo": ("tipo", "tipo de elemento", "tipo elemento"),
    "ubicacion": ("ubicacion", "ubicacion descriptiva", "lugar"),
    "sala": ("sala", "sala del plano", "sala plano", "recinto", "codigo de sala"),
    "estado_operativo": ("estado operativo", "estado"),
    "estado_condicion": ("estado condicion", "estado de condicion", "condicion", "estado fisico"),
    "notas": ("notas", "nota", "observaciones", "observacion", "comentarios"),
    "rack": ("rack", "gabinete", "rack donde esta montado"),
    "foto": ("foto", "fotos", "fotografia"),
}
#: La planilla de puntos de datos: el «Elemento» es la roseta, con su sala.
COLUMNAS_PUNTOS: dict[str, tuple[str, ...]] = {
    "roseta": ("elemento", "roseta", "punto de datos", "descripcion"),
    "etiqueta": ("etiqueta", "rotulo", "rotulo fisico"),
    "tipo": ("tipo", "tipo de elemento"),
    "ubicacion": ("ubicacion", "piso y tramo", "piso tramo"),
    "sala": ("sala", "sala del plano", "sala plano", "recinto", "codigo de sala"),
    "estado_operativo": ("estado operativo", "estado"),
    "estado_condicion": ("estado condicion", "estado de condicion", "condicion", "estado fisico"),
    "notas": ("notas", "nota", "observaciones", "observacion", "comentarios"),
}
#: Posición de cada columna en las planillas del CADI, si no traen encabezado.
POSICIONES_EQUIPO = {
    "modelo": 0, "etiqueta": 1, "tipo": 2, "ubicacion": 3, "estado_operativo": 4,
    "estado_condicion": 5, "notas": 6, "rack": 7, "foto": 8,
}
POSICIONES_PUNTOS = {
    "roseta": 0, "etiqueta": 1, "tipo": 2, "ubicacion": 3, "estado_operativo": 4,
    "estado_condicion": 5, "notas": 6,
}
#: Las de IP, MAC, serie e inventario las reconoce ``importar_edificio.columnas_opcionales``.
OPCIONALES = ("ip", "mac", "serie", "inventario", "gestion")


def clave_de_encabezado(nombre: str) -> str:
    """«Ubicación (Hacia dónde va el cable)» → «ubicacion»; «N° de serie» → «n de serie»."""
    sin_parentesis = re.sub(r"\(.*?\)", " ", nombre)
    return re.sub(r"\s+", " ", re.sub(r"[^a-z ]", " ", normalizar(sin_parentesis))).strip()


@dataclass
class Columnas:
    indices: dict[str, int] = field(default_factory=dict)
    #: Encabezados que no son de ningún campo: no se importan.
    desconocidas: list[str] = field(default_factory=list)
    #: Encabezados mal escritos que se reconocieron: «Etiquta» → «etiqueta».
    corregidas: list[tuple[str, str]] = field(default_factory=list)


def columnas_de(
    encabezado: list[str], campos: dict[str, tuple[str, ...]], posiciones: dict[str, int]
) -> Columnas:
    """En qué columna está cada campo, por su nombre y en cualquier orden.

    Si el encabezado no nombra el tipo, se supone el orden de las planillas
    del CADI: así se leen también las que no traen encabezado.
    """
    nombres = {nombre: campo for campo, admitidos in campos.items() for nombre in admitidos}
    resultado = Columnas()
    for indice, original in enumerate(encabezado):
        clave = clave_de_encabezado(original)
        if not clave:
            continue
        campo = nombres.get(clave)
        if campo is None and (parecido := _parecido(clave, list(nombres))):
            campo = nombres[parecido]
            resultado.corregidas.append((original.strip(), parecido))
        if campo is None:
            if not any(p in clave.split() for p in OPCIONALES):
                resultado.desconocidas.append(original.strip())
            continue
        resultado.indices.setdefault(campo, indice)
    if "tipo" not in resultado.indices:
        return Columnas(indices=dict(posiciones))
    return resultado
