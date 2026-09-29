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
from dataclasses import dataclass, field

from app.models import DefinicionAtributo, Elemento, TipoDato

RE_MAC = re.compile(r"^([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$")

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
        if valor is None or valor == "":
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

    for clave, etiqueta in COMUNES_OBLIGATORIOS:
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
