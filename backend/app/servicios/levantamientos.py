"""Fechas de las visitas a terreno de cada edificio (SOP sección 10.5).

Las planillas no traen la fecha en que se levantó cada elemento, así que se
declara aparte, en ``data/<código>/<código>-levantamiento.csv``: una fila por
visita, con su fecha de inicio y de cierre, los pisos que cubrió y una
observación::

    fecha_inicio,fecha_cierre,pisos,observaciones
    2026-09-15,2026-09-16,P01 P02 P03 P04,Recorrido del edificio

* Cada visita queda en la bitácora ``levantamiento`` del edificio, cerrada si
  tiene fecha de cierre.
* Los elementos de los pisos de la visita toman como fecha del último
  levantamiento la de cierre (la de inicio, si la visita sigue abierta). Una
  fecha posterior que ya tenga el elemento, por ejemplo de una verificación
  registrada desde el visor, no se reemplaza.
* Una visita sin pisos cubre todo el edificio.

Aplicarlo de nuevo no cambia nada: ``iniciar.sh`` lo hace en cada arranque.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import re
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Edificio,
    Elemento,
    EstadoLevantamiento,
    Levantamiento,
    OrigenCambio,
    Piso,
)
from app.servicios.historial import registrar_cambios

#: "P01", "p1" o "1" («Piso 1» se lleva antes a "P1"); el subterráneo es el piso 0.
RE_PISO = re.compile(r"^p?(\d{1,2})$", re.IGNORECASE)


class ArchivoLevantamientoInvalido(ValueError):
    """Una fila del archivo de levantamientos no se puede interpretar."""


@dataclass(frozen=True)
class Visita:
    fecha_inicio: dt.date
    fecha_cierre: dt.date | None
    #: Códigos de piso (``P01``); vacío = todo el edificio.
    pisos: tuple[str, ...]
    observaciones: str | None

    @property
    def fecha(self) -> dt.date:
        """La que toman los elementos: la de cierre o, si sigue abierta, la de inicio."""
        return self.fecha_cierre or self.fecha_inicio

    @property
    def descripcion(self) -> str:
        if self.fecha_cierre and self.fecha_cierre != self.fecha_inicio:
            return f"del {self.fecha_inicio:%d-%m-%Y} al {self.fecha_cierre:%d-%m-%Y}"
        return f"del {self.fecha_inicio:%d-%m-%Y}"


@dataclass
class InformeLevantamiento:
    visitas_nuevas: int = 0
    elementos_fechados: int = 0


def ruta_levantamientos(dir_datos: Path, codigo_edificio: str) -> Path:
    return dir_datos / f"{codigo_edificio.lower()}-levantamiento.csv"


def _fecha(texto: str | None, fila: int, columna: str) -> dt.date | None:
    texto = (texto or "").strip()
    if not texto:
        return None
    try:
        return dt.date.fromisoformat(texto)
    except ValueError:
        raise ArchivoLevantamientoInvalido(
            f"fila {fila}: {columna} «{texto}» no es una fecha AAAA-MM-DD"
        ) from None


def _pisos(texto: str | None, fila: int) -> tuple[str, ...]:
    codigos = []
    # «Piso 3» es un solo piso: se junta antes de separar.
    texto = re.sub(r"piso\s*", "P", texto or "", flags=re.IGNORECASE)
    for parte in re.split(r"[\s,;/]+", texto.strip()):
        if not parte:
            continue
        coincidencia = RE_PISO.match(parte)
        if coincidencia is None:
            raise ArchivoLevantamientoInvalido(
                f"fila {fila}: «{parte}» no es un piso (P01, P02…)"
            )
        codigos.append(f"P{int(coincidencia.group(1)):02d}")
    return tuple(dict.fromkeys(codigos))


def leer_levantamientos(ruta: Path) -> list[Visita]:
    """Las visitas del archivo, en orden de fecha. Sin archivo, ninguna.

    Acepta coma o punto y coma como separador, como las demás planillas.
    """
    if not ruta.is_file():
        return []
    texto = ruta.read_text(encoding="utf-8-sig")
    primera = texto.splitlines()[0] if texto.strip() else ""
    separador = ";" if primera.count(";") > primera.count(",") else ","
    visitas = []
    lector = csv.DictReader(io.StringIO(texto), delimiter=separador)
    for numero, fila in enumerate(lector, start=2):
        fila = {
            (clave or "").strip().lower(): (valor or "")
            for clave, valor in fila.items()
        }
        if not any(valor.strip() for valor in fila.values()):
            continue
        inicio = _fecha(fila.get("fecha_inicio"), numero, "fecha_inicio")
        if inicio is None:
            raise ArchivoLevantamientoInvalido(f"fila {numero}: falta la fecha_inicio")
        cierre = _fecha(fila.get("fecha_cierre"), numero, "fecha_cierre")
        if cierre is not None and cierre < inicio:
            raise ArchivoLevantamientoInvalido(
                f"fila {numero}: la fecha_cierre es anterior a la fecha_inicio"
            )
        visitas.append(
            Visita(
                fecha_inicio=inicio,
                fecha_cierre=cierre,
                pisos=_pisos(fila.get("pisos"), numero),
                observaciones=fila.get("observaciones", "").strip() or None,
            )
        )
    return sorted(visitas, key=lambda visita: visita.fecha)


def aplicar_levantamientos(
    sesion: Session, edificio: Edificio, visitas: list[Visita]
) -> InformeLevantamiento:
    """Registra las visitas en la bitácora y fecha los elementos que cubrieron."""
    informe = InformeLevantamiento()
    for visita in visitas:
        registro = sesion.scalar(
            select(Levantamiento).where(
                Levantamiento.edificio_id == edificio.id,
                Levantamiento.fecha_inicio == visita.fecha_inicio,
            )
        )
        if registro is None:
            registro = Levantamiento(
                edificio=edificio, fecha_inicio=visita.fecha_inicio
            )
            sesion.add(registro)
            informe.visitas_nuevas += 1
        registro.fecha_cierre = visita.fecha_cierre
        registro.estado = (
            EstadoLevantamiento.CERRADO
            if visita.fecha_cierre
            else EstadoLevantamiento.EN_CURSO
        )
        registro.observaciones = visita.observaciones

        consulta = select(Elemento).where(
            Elemento.edificio_id == edificio.id, Elemento.activo.is_(True)
        )
        if visita.pisos:
            consulta = consulta.join(Piso, Elemento.piso_id == Piso.id).where(
                Piso.codigo.in_(visita.pisos)
            )
        for elemento in sesion.scalars(consulta).unique().all():
            actual = elemento.fecha_ultimo_levantamiento
            if actual is not None and actual >= visita.fecha:
                continue
            registrar_cambios(
                sesion,
                elemento,
                {"fecha_ultimo_levantamiento": visita.fecha},
                origen=OrigenCambio.SISTEMA,
                usuario="levantamiento",
                comentario=f"Visita a terreno {visita.descripcion}",
            )
            informe.elementos_fechados += 1
    sesion.flush()
    return informe
