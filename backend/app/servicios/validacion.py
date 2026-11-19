"""Validación de fichas y cálculo de completitud.

Dos niveles deliberadamente distintos:

* **Validación de forma** (:func:`validar_atributos`): rechaza datos mal
  tipados o claves ajenas a la ficha del tipo. Es un error de la petición.
* **Completitud** (:func:`evaluar_completitud`): mide cuántos atributos
  obligatorios faltan, sin bloquear la carga. El levantamiento en terreno es
  incremental — el técnico registra lo que ve y completa después — y el
  reporte "Elementos incompletos por edificio" (SOP sección 10.5, punto 22)
  es justamente el que persigue esos pendientes.
"""

from __future__ import annotations

import datetime as dt
import ipaddress
import re
import unicodedata
from dataclasses import dataclass, field
from difflib import get_close_matches

from app.models import DefinicionAtributo, Elemento, TipoDato

RE_MAC = re.compile(r"^([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$")
#: N° de Inventario UMAG: solo cifras.
RE_INVENTARIO = re.compile(r"^\d{1,30}$")

# --------------------------------------------------------------------------
# Normalización: todo dato se guarda de una sola forma, venga del visor, de la
# API o de una planilla
# --------------------------------------------------------------------------
#: Espacios que Excel o una página web dejan en un texto: el duro (NBSP) y los finos.
RE_ESPACIOS_RAROS = re.compile("[\u00a0\u1680\u2000-\u200a\u202f\u205f\u3000]")
#: Lo que no se ve y no debe guardarse: controles y caracteres de ancho cero.
RE_INVISIBLES = re.compile("[\u200b-\u200d\u2060\ufeff\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def limpiar_texto(valor: object, *, multilinea: bool = False) -> str | None:
    """Sin espacios al comienzo ni al final, un solo espacio entre palabras y sin
    caracteres invisibles. Con ``multilinea`` conserva los saltos de línea (las
    observaciones). Vacío es ``None``: sin dato."""
    if valor is None:
        return None
    texto = RE_INVISIBLES.sub("", RE_ESPACIOS_RAROS.sub(" ", str(valor)))
    if multilinea:
        lineas = texto.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        texto = "\n".join(re.sub(r"[ \t]+", " ", linea).strip() for linea in lineas).strip()
        texto = re.sub(r"\n{3,}", "\n\n", texto)
    else:
        texto = re.sub(r"\s+", " ", texto).strip()
    return texto or None


def _sin_espacios(valor: str) -> str:
    return re.sub(r"\s+", "", RE_INVISIBLES.sub("", RE_ESPACIOS_RAROS.sub(" ", valor)))


def _ip(valor: str) -> str:
    """«10.40.0.2», también con espacios («10.40.0. 2»), comas en vez de puntos
    o ceros a la izquierda («010.040.000.002»)."""
    texto = _sin_espacios(valor)
    if re.fullmatch(r"\d{1,3}(?:[.,]\d{1,3}){3}", texto):
        octetos = [int(o) for o in re.split(r"[.,]", texto)]
        texto = ".".join(map(str, octetos))
    try:
        return str(ipaddress.ip_address(texto))
    except ValueError:
        raise ValueError("no es una dirección IP válida") from None


def _mac(valor: str) -> str:
    """AA:BB:CC:DD:EE:FF, escrita con guiones, puntos (aabb.ccdd.eeff, como
    la muestran los equipos Cisco), espacios o sin separadores."""
    cifras = re.sub(r"[:.\-]", "", _sin_espacios(valor))
    if not re.fullmatch(r"[0-9A-Fa-f]{12}", cifras):
        raise ValueError("debe tener el formato AA:BB:CC:DD:EE:FF")
    cifras = cifras.upper()
    return ":".join(cifras[i : i + 2] for i in range(0, 12, 2))


def _inventario(valor: str) -> str:
    """Solo cifras, con sus ceros iniciales. Se quitan los espacios y los puntos
    o guiones que separan grupos («0045 123», «0045-123»); un «.0» final es
    Excel, que tomó el número como decimal."""
    texto = _sin_espacios(valor)
    if re.fullmatch(r"\d+(?:[.,]\d+)?[eE][+-]?\d+", texto):
        raise ValueError(
            "Excel lo convirtió en notación científica y perdió cifras: dé formato de texto "
            "a la columna y vuelva a escribirlo"
        )
    texto = re.sub(r"[.,]0+$", "", texto)
    texto = re.sub(r"[.\-_/]", "", texto)
    if not RE_INVENTARIO.match(texto):
        raise ValueError("el N° de inventario UMAG lleva solo cifras, sin letras ni signos")
    return texto


def _serie(valor: str) -> str:
    """El número de serie del fabricante, en mayúsculas y sin espacios."""
    return _sin_espacios(valor).upper()


#: Cómo se guardan la IP, la MAC, el N° de serie y el N° de inventario de un
#: equipo, al darlo de alta, al editarlo y al importar planillas. Las que
#: pueden fallar lanzan ValueError con el motivo.
NORMALIZAR = {
    "direccion_ip": _ip,
    "direccion_mac": _mac,
    "numero_serie": _serie,
    "numero_inventario": _inventario,
}


def leer_fecha(valor: object) -> dt.date | None:
    """AAAA-MM-DD, o como la exporta Excel con la configuración regional de
    Chile: 17-11-2026 o 17/11/2026. None si no es una fecha."""
    if isinstance(valor, dt.datetime):
        return valor.date()
    if isinstance(valor, dt.date):
        return valor
    texto = limpiar_texto(valor) or ""
    try:
        return dt.date.fromisoformat(texto)
    except ValueError:
        pass
    if coincidencia := re.fullmatch(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})", texto):
        dia, mes, anio = (int(g) for g in coincidencia.groups())
        try:
            return dt.date(anio, mes, dia)
        except ValueError:
            return None
    return None


VERDADEROS = {"si", "s", "yes", "y", "true", "verdadero", "1", "x"}
FALSOS = {"no", "n", "false", "falso", "0"}


def _sin_tildes(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()


def normalizar_atributo(definicion: DefinicionAtributo, valor: object) -> object:
    """El valor de un atributo de la ficha como se guarda: un número escrito
    como texto («24», «12,5», «1500 VA») pasa a número; «sí» y «no», a
    verdadero y falso; «a, b» a una lista; la fecha a AAAA-MM-DD; una opción
    escrita con otras mayúsculas, sin tildes o con un error menor, a la del
    catálogo. Lo que no se puede interpretar se deja como vino, para que la
    validación diga qué está mal."""
    if not isinstance(valor, str):
        if definicion.tipo_dato is TipoDato.LISTA and isinstance(valor, list):
            return [v for v in (limpiar_texto(x) if isinstance(x, str) else x for x in valor) if v not in (None, "")]
        return valor
    texto = limpiar_texto(valor, multilinea=definicion.tipo_dato is TipoDato.TEXTO)
    if texto is None:
        return None
    tipo = definicion.tipo_dato
    if tipo is TipoDato.NUMERO:
        if coincidencia := re.fullmatch(r"(-?\d+(?:[.,]\d+)?)\s*[A-Za-z%°]{0,10}\.?", texto):
            numero = coincidencia.group(1).replace(",", ".")
            return float(numero) if "." in numero else int(numero)
        return texto
    if tipo is TipoDato.BOOLEANO:
        clave = _sin_tildes(texto)
        if clave in VERDADEROS:
            return True
        if clave in FALSOS:
            return False
        return texto
    if tipo is TipoDato.LISTA:
        return [p for p in (limpiar_texto(x) for x in re.split(r"[,;\n]", texto)) if p]
    if tipo is TipoDato.FECHA:
        fecha = leer_fecha(texto)
        return fecha.isoformat() if fecha else texto
    if tipo is TipoDato.IP:
        try:
            return _ip(texto)
        except ValueError:
            return texto
    if tipo is TipoDato.MAC:
        try:
            return _mac(texto)
        except ValueError:
            return texto
    if tipo is TipoDato.ENUM:
        opciones = [str(o) for o in (definicion.opciones or [])]
        por_clave = {_sin_tildes(o): o for o in opciones}
        clave = _sin_tildes(texto)
        if clave in por_clave:
            return por_clave[clave]
        parecida = get_close_matches(clave, list(por_clave), n=1, cutoff=0.8)
        return por_clave[parecida[0]] if parecida else texto
    return texto

#: Atributos comunes obligatorios del SOP sección 9.1 que se controlan como
#: columnas del elemento. ``codigo``, ``tipo``, ``edificio`` y ``piso`` no
#: aparecen porque el modelo los exige al crear la fila.
COMUNES_OBLIGATORIOS: tuple[tuple[str, str], ...] = (
    ("coordenadas", "Coordenadas sobre el plano (x, y)"),
    ("ubicacion_descriptiva", "Ubicación descriptiva"),
    ("estado_operativo", "Estado operativo"),
    ("estado_condicion", "Estado de condición"),
    ("fecha_instalacion", "Fecha de instalación"),
    ("fecha_ultimo_levantamiento", "Fecha del último levantamiento"),
    ("responsable_id", "Responsable"),
)

#: Columnas del elemento que la ficha de su tipo exige en el SOP sección 9.2:
#: los equipos llevan su N° de serie y su N° de Inventario UMAG.
POR_TIPO_OBLIGATORIOS: dict[str, tuple[tuple[str, str], ...]] = dict.fromkeys(
    ("SW", "AP", "UPS", "MC", "ONT"),
    (("numero_serie", "N° de serie"), ("numero_inventario", "N° de Inventario UMAG")),
)


class AtributosInvalidos(ValueError):
    def __init__(self, errores: list[str]) -> None:
        self.errores = errores
        super().__init__("; ".join(errores))


@dataclass
class Completitud:
    total_obligatorios: int
    completos: int
    faltantes: list[dict[str, str]] = field(default_factory=list)

    @property
    def porcentaje(self) -> float:
        if self.total_obligatorios == 0:
            return 100.0
        return round(100.0 * self.completos / self.total_obligatorios, 1)

    @property
    def completo(self) -> bool:
        return not self.faltantes


def _valor_valido(definicion: DefinicionAtributo, valor: object) -> str | None:
    """Devuelve el mensaje de error, o ``None`` si el valor es aceptable."""
    tipo = definicion.tipo_dato

    if tipo is TipoDato.NUMERO:
        if isinstance(valor, bool) or not isinstance(valor, (int, float)):
            return f"'{definicion.clave}' debe ser numérico"
    elif tipo is TipoDato.BOOLEANO:
        if not isinstance(valor, bool):
            return f"'{definicion.clave}' debe ser booleano"
    elif tipo is TipoDato.LISTA:
        if not isinstance(valor, list):
            return f"'{definicion.clave}' debe ser una lista"
    elif tipo is TipoDato.FECHA:
        if not isinstance(valor, str):
            return f"'{definicion.clave}' debe ser una fecha ISO (AAAA-MM-DD)"
        try:
            dt.date.fromisoformat(valor)
        except ValueError:
            return f"'{definicion.clave}' debe ser una fecha ISO (AAAA-MM-DD)"
    elif tipo is TipoDato.IP:
        try:
            ipaddress.ip_address(str(valor))
        except ValueError:
            return f"'{definicion.clave}' no es una dirección IP válida"
    elif tipo is TipoDato.MAC:
        if not RE_MAC.match(str(valor)):
            return f"'{definicion.clave}' debe tener formato AA:BB:CC:DD:EE:FF"
    elif tipo is TipoDato.ENUM:
        opciones = definicion.opciones or []
        if opciones and valor not in opciones:
            return f"'{definicion.clave}' debe ser uno de: {', '.join(map(str, opciones))}"

    return None


def validar_atributos(
    definiciones: list[DefinicionAtributo],
    atributos: dict | None,
    *,
    rechazar_desconocidos: bool = True,
) -> dict:
    """Valida la ficha específica contra el catálogo del tipo.

    Lanza :class:`AtributosInvalidos` si hay claves ajenas o valores mal
    tipados. Los valores ``None`` se descartan (equivalen a "sin dato").
    """
    atributos = atributos or {}
    por_clave = {d.clave: d for d in definiciones}
    errores: list[str] = []
    limpio: dict = {}

    for clave, valor in atributos.items():
        definicion = por_clave.get(clave)
        if definicion is None:
            if rechazar_desconocidos:
                errores.append(
                    f"'{clave}' no pertenece a la ficha de este tipo de elemento"
                )
            continue
        valor = normalizar_atributo(definicion, valor)
        if valor is None or valor == "" or valor == []:
            continue
        error = _valor_valido(definicion, valor)
        if error:
            errores.append(error)
        else:
            limpio[clave] = valor

    if errores:
        raise AtributosInvalidos(errores)
    return limpio


def evaluar_completitud(
    elemento: Elemento, definiciones: list[DefinicionAtributo] | None = None
) -> Completitud:
    """Mide el cumplimiento del mínimo obligatorio del SOP sección 9."""
    if definiciones is None:
        definiciones = list(elemento.tipo.atributos)

    faltantes: list[dict[str, str]] = []
    total = 0

    del_tipo = POR_TIPO_OBLIGATORIOS.get(elemento.tipo.codigo, ())
    for clave, etiqueta in (*COMUNES_OBLIGATORIOS, *del_tipo):
        total += 1
        if clave == "coordenadas":
            # Lo montado en un rack o punto de datos toma las del contenedor.
            presente = elemento.representante_en_plano.tiene_coordenadas
        else:
            presente = getattr(elemento, clave, None) not in (None, "")
        if not presente:
            faltantes.append({"clave": clave, "etiqueta": etiqueta, "origen": "comun"})

    atributos = elemento.atributos or {}
    for definicion in definiciones:
        if not definicion.obligatorio:
            continue
        total += 1
        valor = atributos.get(definicion.clave)
        if valor in (None, "", []):
            faltantes.append(
                {
                    "clave": definicion.clave,
                    "etiqueta": definicion.etiqueta,
                    "origen": "ficha",
                }
            )

    return Completitud(
        total_obligatorios=total, completos=total - len(faltantes), faltantes=faltantes
    )
