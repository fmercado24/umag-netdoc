"""Elementos lógicos: VLANs, subredes y enlaces entre elementos."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import or_, select

from app.api.deps import (
    SesionBD,
    edificio_permitido,
    exigir_todos_los_edificios,
    obtener_edificio,
    obtener_elemento,
)
from app.models import Edificio, Elemento, Enlace, Vlan
from app.schemas.logico import EnlaceCrear, EnlaceLeer, VlanCrear, VlanLeer

router = APIRouter(tags=["elementos lógicos"])


@router.get("/vlans", response_model=list[VlanLeer])
def listar_vlans(sesion: SesionBD, edificio: str | None = None):
    consulta = select(Vlan).order_by(Vlan.numero)
    permitido = edificio_permitido(sesion)
    if edificio:
        ed = obtener_edificio(sesion, edificio)
        consulta = consulta.where(Vlan.edificio_id == ed.id)
    elif permitido:
        # Las de su edificio y las de campus, que también llegan a él.
        consulta = consulta.outerjoin(Edificio, Vlan.edificio_id == Edificio.id).where(
            or_(Vlan.edificio_id.is_(None), Edificio.codigo == permitido)
        )
    return sesion.scalars(consulta).all()


@router.post("/vlans", response_model=VlanLeer, status_code=status.HTTP_201_CREATED)
def crear_vlan(datos: VlanCrear, sesion: SesionBD):
    edificio_id = None
    if datos.edificio:
        edificio_id = obtener_edificio(sesion, datos.edificio).id
    else:
        exigir_todos_los_edificios(sesion)

    # El número se repite entre edificios, no dentro de uno (ni entre las de campus).
    mismo_ambito = Vlan.edificio_id == edificio_id if edificio_id else Vlan.edificio_id.is_(None)
    if sesion.scalar(select(Vlan).where(Vlan.numero == datos.numero, mismo_ambito)):
        donde = f"en {datos.edificio.upper()}" if datos.edificio else "de campus"
        raise HTTPException(status.HTTP_409_CONFLICT, f"Ya existe la VLAN {datos.numero} {donde}")

    vlan = Vlan(**{**datos.model_dump(exclude={"edificio"}), "edificio_id": edificio_id})
    sesion.add(vlan)
    sesion.flush()
    return vlan


@router.get("/enlaces", response_model=list[EnlaceLeer])
def listar_enlaces(sesion: SesionBD, elemento: str | None = None):
    consulta = select(Enlace)
    permitido = edificio_permitido(sesion)
    if elemento:
        objetivo = obtener_elemento(sesion, elemento)
        consulta = consulta.where(
            (Enlace.origen_id == objetivo.id) | (Enlace.destino_id == objetivo.id)
        )
    elif permitido:
        consulta = (
            consulta.join(Elemento, Enlace.origen_id == Elemento.id)
            .join(Edificio, Elemento.edificio_id == Edificio.id)
            .where(Edificio.codigo == permitido)
        )
    return sesion.scalars(consulta).all()


@router.post("/enlaces", response_model=EnlaceLeer, status_code=status.HTTP_201_CREATED)
def crear_enlace(datos: EnlaceCrear, sesion: SesionBD):
    """Registra un enlace físico: uplink de switch o mapeo patch panel →
    punto de datos. El destino puede quedar como texto si todavía no está
    documentado como elemento."""
    origen = obtener_elemento(sesion, datos.origen_codigo)
    destino = obtener_elemento(sesion, datos.destino_codigo) if datos.destino_codigo else None

    enlace = Enlace(
        origen_id=origen.id,
        destino_id=destino.id if destino else None,
        **datos.model_dump(exclude={"origen_codigo", "destino_codigo"}),
    )
    sesion.add(enlace)
    sesion.flush()
    return enlace
