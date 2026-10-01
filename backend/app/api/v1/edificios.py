"""Navegación multi-edificio: edificio → piso → plano."""

from __future__ import annotations

from fastapi import (
    APIRouter,
    BackgroundTasks,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from sqlalchemy import select

from app.api.deps import SesionBD, obtener_edificio, obtener_piso, obtener_tramo
from app.models import Edificio, OrigenCambio, Piso, Tramo
from app.schemas.organizacion import (
    EdificioCrear,
    EdificioDetalle,
    EdificioLeer,
    PisoCrear,
    PisoLeer,
    PlanoLeer,
    TramoCrear,
    TramoLeer,
)
from app.servicios.planos import (
    FormatoNoAdmitido,
    NombreLaminaInvalido,
    SvgInvalido,
    guardar_plano,
    trasladar_posiciones,
)
from app.servicios.teselas import asegurar_teselas

router = APIRouter(prefix="/edificios", tags=["edificios"])


@router.get("", response_model=list[EdificioLeer])
def listar_edificios(sesion: SesionBD, solo_activos: bool = True):
    consulta = select(Edificio).order_by(Edificio.codigo)
    if solo_activos:
        consulta = consulta.where(Edificio.activo.is_(True))
    return sesion.scalars(consulta).all()


@router.post("", response_model=EdificioLeer, status_code=status.HTTP_201_CREATED)
def crear_edificio(datos: EdificioCrear, sesion: SesionBD):
    codigo = datos.codigo.upper()
    if sesion.scalar(select(Edificio).where(Edificio.codigo == codigo)):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Ya existe el edificio '{codigo}'")
    edificio = Edificio(**{**datos.model_dump(), "codigo": codigo})
    sesion.add(edificio)
    sesion.flush()
    return edificio


@router.get("/{codigo}", response_model=EdificioDetalle)
def obtener_edificio_detalle(codigo: str, sesion: SesionBD):
    return obtener_edificio(sesion, codigo)


@router.get("/{codigo}/pisos", response_model=list[PisoLeer])
def listar_pisos(codigo: str, sesion: SesionBD):
    return obtener_edificio(sesion, codigo).pisos


@router.post("/{codigo}/pisos", response_model=PisoLeer, status_code=status.HTTP_201_CREATED)
def crear_piso(codigo: str, datos: PisoCrear, sesion: SesionBD):
    edificio = obtener_edificio(sesion, codigo)
    codigo_piso = datos.codigo.upper()
    existente = sesion.scalar(
        select(Piso).where(Piso.edificio_id == edificio.id, Piso.codigo == codigo_piso)
    )
    if existente is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"El edificio '{edificio.codigo}' ya tiene el piso '{codigo_piso}'",
        )
    piso = Piso(
        edificio_id=edificio.id, codigo=codigo_piso, nombre=datos.nombre, orden=datos.orden
    )
    sesion.add(piso)
    sesion.flush()
    return piso


@router.post(
    "/{codigo}/pisos/{codigo_piso}/tramos",
    response_model=TramoLeer,
    status_code=status.HTTP_201_CREATED,
)
def crear_tramo(codigo: str, codigo_piso: str, datos: TramoCrear, sesion: SesionBD):
    edificio = obtener_edificio(sesion, codigo)
    piso = obtener_piso(sesion, edificio, codigo_piso)
    codigo_tramo = datos.codigo.upper()
    existente = sesion.scalar(
        select(Tramo).where(Tramo.piso_id == piso.id, Tramo.codigo == codigo_tramo)
    )
    if existente is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"El piso '{piso.codigo}' ya tiene el tramo '{codigo_tramo}'"
        )
    tramo = Tramo(piso_id=piso.id, codigo=codigo_tramo, nombre=datos.nombre)
    sesion.add(tramo)
    sesion.flush()
    return tramo


@router.get("/{codigo}/pisos/{codigo_piso}/plano", response_model=PlanoLeer)
def obtener_plano(codigo: str, codigo_piso: str, sesion: SesionBD, tramo: str | None = None):
    """Plano vigente del tramo, o el del piso completo si el tramo no tiene uno."""
    edificio = obtener_edificio(sesion, codigo)
    piso = obtener_piso(sesion, edificio, codigo_piso)
    tramo_sel = obtener_tramo(sesion, piso, tramo)
    plano = piso.plano_para(tramo_sel)
    if plano is None:
        ubicacion = f"{edificio.codigo}-{piso.codigo}" + (f"-{tramo_sel.codigo}" if tramo_sel else "")
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"'{ubicacion}' aún no tiene un plano vigente cargado",
        )
    return plano


@router.post(
    "/{codigo}/pisos/{codigo_piso}/plano",
    response_model=PlanoLeer,
    status_code=status.HTTP_201_CREATED,
)
def cargar_plano(
    codigo: str,
    codigo_piso: str,
    sesion: SesionBD,
    tareas: BackgroundTasks,
    archivo: UploadFile = File(
        ...,
        description="Plano en SVG, PNG, JPG o PDF, con nombre <edificio>-p<piso>[-t<tramo>].<ext>",
    ),
    ancho_px: int = Form(..., gt=0, description="Ancho del plano en sus propias unidades"),
    alto_px: int = Form(..., gt=0, description="Alto del plano en sus propias unidades"),
    tramo: str | None = Form(None, description="Tramo que cubre la lámina; vacío = piso completo"),
    nombre: str | None = Form(None),
    version: str | None = Form(None),
    notas: str | None = Form(None),
):
    """Carga el plano del piso (o de uno de sus tramos) y lo marca como vigente.

    El archivo debe llamarse según la nomenclatura de las láminas y
    corresponder al destino: ``cadi-p01-t2.svg`` solo se acepta para el tramo
    T2 del piso P01 del CADI.

    ``ancho_px`` y ``alto_px`` definen el sistema de coordenadas en que se
    guardan las posiciones de los elementos, por eso se piden explícitamente
    en lugar de inferirlos: fija la referencia aunque el archivo se
    reemplace por una versión reescalada.

    Las teselas con que el visor muestra la lámina se generan después de
    responder: mientras tanto se ve la lámina original.

    Si ya había una lámina para ese piso–tramo, queda como histórica. Los
    elementos ubicados sobre ella pasan a la nueva si el tamaño es el mismo;
    si cambió, quedan sin ubicar (las coordenadas anteriores quedan en su
    historial).
    """
    edificio = obtener_edificio(sesion, codigo)
    piso = obtener_piso(sesion, edificio, codigo_piso)
    tramo_sel = obtener_tramo(sesion, piso, tramo)
    try:
        plano = guardar_plano(
            sesion,
            piso,
            tramo_sel,
            archivo.filename or "plano",
            archivo.file.read(),
            ancho_px=ancho_px,
            alto_px=alto_px,
            nombre=nombre,
            version=version,
            notas=notas,
        )
    except FormatoNoAdmitido as exc:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(exc)) from exc
    except (SvgInvalido, NombreLaminaInvalido) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    trasladar_posiciones(sesion, plano, origen=OrigenCambio.MANUAL)
    tareas.add_task(asegurar_teselas, plano.archivo, plano.ancho_px)
    return plano
