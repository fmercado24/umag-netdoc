"""Registro del historial de cambios por elemento (SOP secciones 11 y 12)."""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

from sqlalchemy.orm import Session

from app.models import Elemento, HistorialElemento, OrigenCambio

#: Campos cuyo cambio se registra en la bitácora. Se excluyen las marcas de
#: tiempo automáticas y la clave primaria.
CAMPOS_AUDITADOS: tuple[str, ...] = (
    "codigo",
    "etiqueta",
    "tipo_elemento_id",
    "edificio_id",
    "piso_id",
    "tramo_id",
    "tramo_lamina_id",
    "ubicacion_descriptiva",
    "numero_recinto",
    "padre_id",
    "unidad_rack",
    "plano_id",
    "pos_x",
    "pos_y",
    "estado_operativo",
    "estado_condicion",
    "criticidad",
    "marca",
    "modelo",
    "numero_serie",
    "direccion_mac",
    "direccion_ip",
    "fecha_instalacion",
    "fecha_ultimo_levantamiento",
    "responsable_id",
    "observaciones",
    "atributos",
    "activo",
)


def _a_texto(valor: Any) -> str | None:
    if valor is None:
        return None
    if isinstance(valor, (dict, list)):
        return json.dumps(valor, ensure_ascii=False, sort_keys=True)
    if isinstance(valor, (dt.date, dt.datetime)):
        return valor.isoformat()
    if hasattr(valor, "value"):  # Enum del dominio
        return str(valor.value)
    return str(valor)


def _quien(sesion: Session, usuario: str | None) -> str | None:
    """El nombre que se escribió en «Registrado por» o, si no, la cuenta con que
    se ingresó (la deja ``api.deps`` en la sesión)."""
    acceso = sesion.info.get("acceso")
    return usuario or (acceso.usuario if acceso else None)


def registrar_cambios(
    sesion: Session,
    elemento: Elemento,
    cambios: dict[str, Any],
    *,
    origen: OrigenCambio = OrigenCambio.MANUAL,
    usuario: str | None = None,
    comentario: str | None = None,
) -> list[HistorialElemento]:
    """Aplica ``cambios`` sobre el elemento y deja una entrada por campo.

    Devuelve las entradas creadas; una lista vacía significa que la petición
    no modificaba nada.
    """
    entradas: list[HistorialElemento] = []
    usuario = _quien(sesion, usuario)

    for campo, valor_nuevo in cambios.items():
        if campo not in CAMPOS_AUDITADOS:
            continue
        valor_anterior = getattr(elemento, campo)
        if valor_anterior == valor_nuevo:
            continue

        setattr(elemento, campo, valor_nuevo)
        entrada = HistorialElemento(
            elemento=elemento,
            campo=campo,
            valor_anterior=_a_texto(valor_anterior),
            valor_nuevo=_a_texto(valor_nuevo),
            origen=origen,
            usuario=usuario,
            comentario=comentario,
        )
        sesion.add(entrada)
        entradas.append(entrada)

    return entradas


def registrar_alta(
    sesion: Session,
    elemento: Elemento,
    *,
    origen: OrigenCambio = OrigenCambio.MANUAL,
    usuario: str | None = None,
    comentario: str | None = None,
) -> HistorialElemento:
    """Primera entrada de la bitácora: el alta del elemento."""
    entrada = HistorialElemento(
        elemento=elemento,
        campo="alta",
        valor_anterior=None,
        valor_nuevo=elemento.codigo,
        origen=origen,
        usuario=_quien(sesion, usuario),
        comentario=comentario or "Alta del elemento en el sistema",
    )
    sesion.add(entrada)
    return entrada
