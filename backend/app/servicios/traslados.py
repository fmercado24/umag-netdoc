"""Traslado de un elemento a otro piso o tramo de su edificio.

El código dice dónde está el elemento (``CADI-SW03-P01-T1``), así que cambia con
él, y el anterior queda reservado: nunca se reasigna (SOP sección 8.5) y sigue
encontrando al elemento, para que no se rompa lo que aún lo use (ver
``codigos.elemento_por_codigo``).

* En el mismo piso cambia solo el tramo: el correlativo es por piso.
* En otro piso conserva su número si allí está libre, para no perder de vista
  que es el mismo equipo (en el CADI, el rack N°4 es el ``R04`` de los rótulos de
  sus puntos de datos); si no, toma el siguiente.
* Un punto de datos conserva su rack y puerto: ``…-R04-D17``.

Lo montado en un contenedor viaja con él. Lo que solo está conectado (un AP, una
UPS) está en otro lugar físico: si el rack cambia de piso, deja de estar conectado.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import Elemento, HistorialElemento, OrigenCambio, Piso, Tramo
from app.models.elemento import TIPOS_CONECTADOS_AL_CONTENEDOR
from app.servicios.codigos import (
    PREFIJO_SIN_ROTULO,
    CodigoInvalido,
    codigo_ocupado,
    construir_codigo,
    correlativos_usados,
    descomponer_codigo,
    siguiente_sin_rotulo,
)
from app.servicios.historial import registrar_cambios
from app.servicios.recintos import ubicar_en_recinto


class TrasladoInvalido(ValueError):
    """El traslado no se puede hacer: ya está ahí, o el código está ocupado."""


@dataclass(frozen=True)
class Movimiento:
    elemento: Elemento
    codigo: str
    correlativo: int | None


@dataclass(frozen=True)
class PlanTraslado:
    piso: Piso
    tramo: Tramo | None
    #: Primero el elemento y después lo que tiene montado, que viaja con él.
    movimientos: list[Movimiento]
    #: Lo conectado a él que deja de estarlo por quedar en otro piso.
    desconectados: list[Elemento]

    @property
    def elemento(self) -> Elemento:
        return self.movimientos[0].elemento

    @property
    def cambia_de_piso(self) -> bool:
        return self.piso.id != self.elemento.piso_id

    @property
    def nombre_destino(self) -> str:
        return ubicacion_en_texto(self.piso, self.tramo)

    @property
    def sale_de_su_rack(self) -> bool:
        """El rack se queda donde está: montado en él, no puede irse a otro tramo."""
        elemento = self.elemento
        padre = elemento.padre
        if padre is None:
            return False
        if self.cambia_de_piso:
            return True
        return elemento.montado and padre.tramo_id != (self.tramo.id if self.tramo else None)


def ubicacion_en_texto(piso: Piso, tramo: Tramo | None) -> str:
    return f"{piso.codigo}-{tramo.codigo}" if tramo else piso.codigo


def _montados(elemento: Elemento) -> list[Elemento]:
    """Lo que está físicamente dentro, a cualquier profundidad."""
    encontrados: list[Elemento] = []
    vistos = {elemento.id}  # guarda contra ciclos padre → hijo mal cargados

    def recorrer(contenedor: Elemento) -> None:
        for hijo in contenedor.hijos:
            if hijo.activo and hijo.montado and hijo.id not in vistos:
                vistos.add(hijo.id)
                encontrados.append(hijo)
                recorrer(hijo)

    recorrer(elemento)
    return encontrados


def _codigo_en_destino(
    sesion: Session,
    elemento: Elemento,
    piso: Piso,
    tramo: Tramo | None,
    reservados: dict[tuple[int, int], set[int]],
) -> tuple[str, int | None]:
    try:
        detalle = descomponer_codigo(elemento.codigo).detalle
    except CodigoInvalido:
        detalle = None
    ubicacion = {
        "edificio": elemento.edificio.codigo,
        "tipo": elemento.tipo.codigo,
        "piso": piso.codigo,
        "tramo": tramo.codigo if tramo else None,
    }

    if not elemento.tipo.usa_correlativo:
        # Sin puerto conocido no hay nada que conservar: el que toque en el destino.
        if detalle is None or detalle.startswith(PREFIJO_SIN_ROTULO):
            detalle = siguiente_sin_rotulo(sesion, construir_codigo(**ubicacion))
        codigo = construir_codigo(detalle=detalle, **ubicacion)
        if codigo_ocupado(sesion, codigo, salvo=elemento.id):
            raise TrasladoInvalido(
                f"Ya existe {codigo}: ese puerto ya está documentado en el destino. "
                "Los códigos no se reutilizan (SOP 8.5)."
            )
        return codigo, None

    # Lo que este mismo traslado ya asignó aún no está en la base.
    asignados = reservados[(elemento.tipo_elemento_id, piso.id)]
    usados = asignados | correlativos_usados(
        sesion,
        edificio_id=elemento.edificio_id,
        tipo_elemento_id=elemento.tipo_elemento_id,
        piso_id=piso.id,
        salvo=elemento.id,
    )
    correlativo = elemento.correlativo
    if correlativo is None or correlativo in usados:
        correlativo = max(usados, default=0) + 1
    asignados.add(correlativo)
    return construir_codigo(correlativo=correlativo, detalle=detalle, **ubicacion), correlativo


def planificar(sesion: Session, elemento: Elemento, piso: Piso, tramo: Tramo | None) -> PlanTraslado:
    """Qué pasaría, sin cambiar nada. Lanza ``TrasladoInvalido`` si no se puede."""
    if elemento.piso_id == piso.id and elemento.tramo_id == (tramo.id if tramo else None):
        raise TrasladoInvalido(f"{elemento.codigo} ya está en {ubicacion_en_texto(piso, tramo)}")

    reservados: dict[tuple[int, int], set[int]] = defaultdict(set)
    viajan = [elemento, *_montados(elemento)]
    movimientos = [
        Movimiento(e, *_codigo_en_destino(sesion, e, piso, tramo, reservados)) for e in viajan
    ]
    desconectados = (
        [h for e in viajan for h in e.hijos if h.activo and not h.montado]
        if piso.id != elemento.piso_id
        else []
    )
    return PlanTraslado(piso, tramo, movimientos, desconectados)


def conserva_posicion(plan: PlanTraslado) -> bool:
    """Su marcador sigue valiendo solo si se dibuja sobre la misma lámina."""
    elemento = plan.elemento
    plano = plan.piso.plano_para(plan.tramo)
    actual = elemento.plano
    return (
        elemento.tiene_coordenadas
        and actual is not None
        and plano is not None
        and actual.piso_id == plan.piso.id
        and actual.tramo_id == plano.tramo_id
    )


def ejecutar(
    sesion: Session,
    plan: PlanTraslado,
    *,
    ubicacion_descriptiva: str | None,
    numero_recinto: str | None,
    padre: Elemento | None,
    unidad_rack: int | None,
    usuario: str | None = None,
    comentario: str | None = None,
) -> None:
    """Aplica el plan. ``ubicacion_descriptiva``, ``numero_recinto``, ``padre`` y
    ``unidad_rack`` son los valores finales, ya resueltos por quien llama."""
    elemento = plan.elemento
    origen = ubicacion_en_texto(elemento.piso, elemento.tramo)
    destino = plan.nombre_destino
    nota = f"Traslado de {origen} a {destino}" + (f": {comentario}" if comentario else "")
    tramo_id = plan.tramo.id if plan.tramo else None
    cambia_recinto = numero_recinto != elemento.numero_recinto
    # Lo montado está donde esté su rack, pero si este no cambia de sala no se le toca
    # lo que diga de sí mismo.
    lugar = {}
    if plan.cambia_de_piso or ubicacion_descriptiva != elemento.ubicacion_descriptiva:
        lugar["ubicacion_descriptiva"] = ubicacion_descriptiva
    if plan.cambia_de_piso or cambia_recinto:
        lugar["numero_recinto"] = numero_recinto
    queda_montado = (
        padre is not None and elemento.tipo.codigo not in TIPOS_CONECTADOS_AL_CONTENEDOR
    )
    posicion = {}
    if queda_montado or not conserva_posicion(plan):
        posicion = {"plano_id": None, "pos_x": None, "pos_y": None}

    def registrar(objetivo: Elemento, movimiento: Movimiento, cambios: dict, texto: str) -> None:
        sesion.add(
            HistorialElemento(
                elemento=objetivo,
                campo="traslado",
                valor_anterior=ubicacion_en_texto(objetivo.piso, objetivo.tramo),
                valor_nuevo=destino,
                origen=OrigenCambio.MANUAL,
                usuario=usuario,
                comentario=texto,
            )
        )
        objetivo.correlativo = movimiento.correlativo
        registrar_cambios(
            sesion,
            objetivo,
            {
                "codigo": movimiento.codigo,
                "piso_id": plan.piso.id,
                "tramo_id": tramo_id,
                # Vuelve a dibujarse en la lámina de su propio tramo.
                "tramo_lamina_id": None,
                **lugar,
                **cambios,
            },
            usuario=usuario,
            comentario=texto,
        )

    registrar(
        elemento,
        plan.movimientos[0],
        {"padre_id": padre.id if padre else None, "unidad_rack": unidad_rack, **posicion},
        nota,
    )
    for movimiento in plan.movimientos[1:]:
        registrar(
            movimiento.elemento,
            movimiento,
            {},
            f"Se trasladó con {plan.movimientos[0].codigo}, donde está montado",
        )
    for conectado in plan.desconectados:
        registrar_cambios(
            sesion,
            conectado,
            {"padre_id": None},
            usuario=usuario,
            comentario=f"{plan.movimientos[0].codigo} se trasladó a {destino}: ya no está conectado",
        )

    sesion.flush()
    for movimiento in plan.movimientos:
        sesion.expire(movimiento.elemento)
    for conectado in plan.desconectados:
        sesion.expire(conectado)
    sesion.expire(plan.piso, ["planos"])

    # Con el número de una sala de la lámina, queda ahí; un rack, sobre su rótulo.
    if not queda_montado and (cambia_recinto or not elemento.tiene_coordenadas):
        ubicar_en_recinto(sesion, elemento, origen=OrigenCambio.MANUAL, usuario=usuario)
        sesion.flush()
        sesion.expire(elemento)
