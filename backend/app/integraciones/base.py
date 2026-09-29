"""Marco común de los conectores con sistemas externos.

Un conector lleva el inventario de NetDoc a otro sistema (Zabbix, NetBox,
GLPI…) en dos pasos:

1. ``planificar`` compara lo que hay en NetDoc con lo que hay en el sistema y
   devuelve las acciones necesarias, **sin modificar nada**.
2. ``aplicar`` ejecuta una acción y devuelve el id que le asignó el sistema,
   que queda en ``identificador_externo`` para la próxima pasada.

``app.scripts.sincronizar`` hace el recorrido; por omisión solo muestra el
plan y ``--aplicar`` lo ejecuta. Para sumar un sistema: una subclase de
``Conector`` y su entrada en ``app.integraciones.CONECTORES``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal

from app.models import Elemento


class ErrorConector(RuntimeError):
    """El sistema externo rechazó una operación o no respondió."""


@dataclass
class Accion:
    tipo: Literal["crear", "actualizar", "sin_cambios"]
    codigo: str
    #: Lo que se enviará al sistema externo.
    datos: dict = field(default_factory=dict)
    #: Id en el sistema externo, si el registro ya existe.
    id_externo: str | None = None
    #: Qué cambia, para mostrarlo en el plan.
    detalle: str | None = None


class Conector(ABC):
    #: Nombre corto con que se guardan sus ids en ``identificador_externo``.
    sistema: str

    def seleccionar(self, elementos: list[Elemento]) -> list[Elemento]:
        """Qué elementos le interesan al sistema; por omisión, todos."""
        return elementos

    @abstractmethod
    def planificar(self, elementos: list[Elemento]) -> list[Accion]:
        """Acciones para que el sistema refleje a ``elementos``, sin aplicarlas."""

    @abstractmethod
    def aplicar(self, accion: Accion) -> str:
        """Ejecuta ``accion`` y devuelve el id externo del registro."""

    def url_de(self, id_externo: str) -> str | None:
        """Enlace al registro en la interfaz del sistema, si la tiene."""
        return None
