"""Navegación multi-edificio: edificio → piso → plano."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import (
    APIRouter,
    BackgroundTasks,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from sqlalchemy import select

from app.api.deps import (
    SesionBD,
    edificio_permitido,
    exigir_todos_los_edificios,
    obtener_edificio,
    obtener_piso,
    obtener_tramo,
)
from app.core.config import DIR_PROYECTO
from app.models import Edificio, OrigenCambio, Piso, Tramo
from app.schemas.organizacion import (
    CargaConfirmada,
    CargaDePlanos,
    EdificioCrear,
    EdificioDetalle,
    EdificioLeer,
    LaminaPendiente,
    PisoCrear,
    PisoLeer,
    PlanoLeer,
    RecintoLeer,
    TramoCrear,
    TramoLeer,
)
from app.servicios import carga_planos
from app.servicios.novedades import marca_del_edificio
from app.servicios.planos import (
    FormatoNoAdmitido,
    NombreLaminaInvalido,
    SvgInvalido,
    guardar_plano,
    trasladar_posiciones,
)
from app.servicios.recintos import recintos_del_piso, sincronizar_y_ubicar
from app.servicios.teselas import asegurar_teselas

router = APIRouter(prefix="/edificios", tags=["edificios"])


@router.get("", response_model=list[EdificioLeer])
def listar_edificios(sesion: SesionBD, solo_activos: bool = True):
    consulta = select(Edificio).order_by(Edificio.codigo)
    if solo_activos:
        consulta = consulta.where(Edificio.activo.is_(True))
    permitido = edificio_permitido(sesion)
    if permitido:
        consulta = consulta.where(Edificio.codigo == permitido)
    return sesion.scalars(consulta).all()


@router.post("", response_model=EdificioLeer, status_code=status.HTTP_201_CREATED)
def crear_edificio(datos: EdificioCrear, sesion: SesionBD):
    exigir_todos_los_edificios(sesion)
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


@router.get("/{codigo}/novedades")
def novedades(codigo: str, sesion: SesionBD) -> dict:
    """Una marca que cambia cuando cambia algo del edificio.

    El visor la consulta cada pocos segundos para mostrar lo que hacen las demás
    personas: es barata, y solo si no es la que vino con el plano vuelve a pedirlo,
    junto con la ficha abierta. No cuenta como actividad de la sesión
    (``servicios.proteccion``).
    """
    return {"marca": marca_del_edificio(sesion, obtener_edificio(sesion, codigo))}


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


# --- Planos de un edificio vacío, desde el visor (app.servicios.carga_planos) ---


def _estado_de_carga(sesion, edificio: Edificio, revisar: list[str] | None = None) -> CargaDePlanos:
    motivo = carga_planos.motivo_para_no_cargar(sesion, edificio)
    return CargaDePlanos(
        edificio=edificio.codigo,
        permitida=motivo is None,
        motivo=motivo,
        **carga_planos.ejemplos(edificio),
        pendientes=[asdict(p) for p in carga_planos.listar(edificio)] if motivo is None else [],
        revisados=[asdict(carga_planos.revisar(edificio, n)) for n in (revisar or [])],
    )


@router.get("/{codigo}/carga-de-planos", response_model=CargaDePlanos)
def estado_carga_de_planos(
    codigo: str,
    sesion: SesionBD,
    archivo: list[str] = Query(default=[], max_length=200, description="Nombres de archivo a revisar"),
):
    """Si el edificio está vacío (sin planos ni elementos), cómo deben llamarse sus
    planos y los que ya esperan a confirmarse. Con ``archivo`` revisa esos nombres
    antes de subirlos."""
    return _estado_de_carga(sesion, obtener_edificio(sesion, codigo), archivo)


@router.post(
    "/{codigo}/carga-de-planos",
    response_model=LaminaPendiente,
    status_code=status.HTTP_201_CREATED,
)
def subir_plano_pendiente(
    codigo: str,
    sesion: SesionBD,
    archivo: UploadFile = File(..., description="Lámina SVG con nombre <edificio>-p<piso>[-t<tramo>].svg"),
):
    """Sube un plano y lo deja en espera, revisado. Subir otra vez el mismo nombre lo
    reemplaza. Nada queda vigente hasta confirmar."""
    edificio = obtener_edificio(sesion, codigo)
    try:
        return asdict(
            carga_planos.agregar(sesion, edificio, archivo.filename or "plano", archivo.file.read())
        )
    except carga_planos.CargaNoPermitida as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except FormatoNoAdmitido as exc:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(exc)) from exc
    except (SvgInvalido, NombreLaminaInvalido) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


@router.delete("/{codigo}/carga-de-planos/{archivo}", status_code=status.HTTP_204_NO_CONTENT)
def quitar_plano_pendiente(codigo: str, archivo: str, sesion: SesionBD):
    """Saca un plano de la espera."""
    edificio = obtener_edificio(sesion, codigo)
    if not carga_planos.quitar(edificio, archivo):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"«{archivo}» no está en espera")


@router.post("/{codigo}/carga-de-planos/confirmar", response_model=CargaConfirmada)
def confirmar_carga_de_planos(codigo: str, sesion: SesionBD, tareas: BackgroundTasks):
    """Crea los pisos y tramos que nombran los planos en espera y los deja vigentes.

    Las teselas se generan después de responder: mientras tanto el visor muestra
    la lámina original.
    """
    edificio = obtener_edificio(sesion, codigo)
    try:
        resultado = carga_planos.confirmar(sesion, edificio)
    except carga_planos.CargaNoPermitida as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except (FormatoNoAdmitido, SvgInvalido, NombreLaminaInvalido) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    sesion.flush()
    # Las tareas corren cuando la respuesta ya salió y lo nuevo quedó guardado.
    tareas.add_task(carga_planos.descartar_todo, edificio.codigo)
    for plano in resultado.planos:
        tareas.add_task(asegurar_teselas, plano.archivo, plano.ancho_px)
    return CargaConfirmada(
        pisos=resultado.pisos,
        tramos=resultado.tramos,
        planos=[PlanoLeer.model_validate(p) for p in resultado.planos],
    )


@router.get("/{codigo}/pisos/{codigo_piso}/recintos", response_model=list[RecintoLeer])
def listar_recintos(codigo: str, codigo_piso: str, sesion: SesionBD):
    """Los recintos de las láminas vigentes del piso: número, nombre y el punto
    donde se ubican sus elementos (ver ``app.servicios.recintos``)."""
    piso = obtener_piso(sesion, obtener_edificio(sesion, codigo), codigo_piso)
    return sorted(recintos_del_piso(piso), key=lambda r: (r.numero, r.tramo_codigo or ""))


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
    # Si <edificio>-recintos.csv se leyó de esta misma lámina, sus recintos se
    # cargan y lo que no está en el plano se ubica en ellos.
    sesion.flush()
    sesion.expire(piso, ["planos"])
    sincronizar_y_ubicar(sesion, edificio, DIR_PROYECTO / "data" / edificio.codigo.lower())
    tareas.add_task(asegurar_teselas, plano.archivo, plano.ancho_px)
    return plano
