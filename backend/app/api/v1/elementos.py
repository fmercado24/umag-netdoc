"""CRUD de elementos, georreferenciación, historial y evidencia fotográfica."""

from __future__ import annotations

import datetime as dt
import re
import unicodedata

from fastapi import (
    APIRouter,
    File,
    Form,
    HTTPException,
    Path,
    Query,
    UploadFile,
    status,
)
from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import aliased

from app.api.deps import (
    SesionBD,
    obtener_edificio,
    obtener_elemento,
    obtener_piso,
    obtener_tipo,
    obtener_tramo,
)
from app.api.v1.inventario import PATRON_SISTEMA
from app.models import (
    Edificio,
    Elemento,
    ElementoVlan,
    EstadoCondicion,
    EstadoOperativo,
    IdentificadorExterno,
    OrigenCambio,
    Piso,
    TipoElemento,
    Tramo,
    Vlan,
)
from app.models.elemento import TIPOS_CONECTADOS_AL_CONTENEDOR
from app.schemas.elemento import (
    CompletitudLeer,
    ElementoActualizar,
    ElementoCrear,
    ElementoDetalle,
    ElementoEnMapa,
    ElementoLeer,
    ElementoMapa,
    FotografiaLeer,
    HistorialLeer,
    IdentificadorExternoGuardar,
    IdentificadorExternoLeer,
    PaginaElementos,
    PosicionActualizar,
    RespuestaMapa,
)
from app.schemas.logico import VlanAsignar
from app.schemas.organizacion import PlanoLeer, RecintoLeer
from app.servicios.codigos import (
    CodigoInvalido,
    construir_codigo,
    descomponer_codigo,
    siguiente_correlativo,
)
from app.servicios.fotografias import FormatoFotoNoAdmitido, guardar_fotografia
from app.servicios.historial import registrar_alta, registrar_cambios
from app.servicios.recintos import (
    buscar_recinto,
    corresponde_al_piso,
    normalizar_numero,
    numero_de_recinto,
    prefijo_de_piso,
    ubicar_en_recinto,
    ubicar_pendientes,
)
from app.servicios.validacion import (
    AtributosInvalidos,
    evaluar_completitud,
    validar_atributos,
)

router = APIRouter(prefix="/elementos", tags=["elementos"])

# --------------------------------------------------------------------------
# Utilidades internas
# --------------------------------------------------------------------------
def _nombre_seguro(nombre: str) -> str:
    base = unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("_") or "archivo"


def _aplicar_filtros(
    consulta: Select,
    *,
    edificio: str | None,
    piso: str | None,
    tramo: str | None,
    tipo: list[str] | None,
    estado: list[EstadoOperativo] | None,
    condicion: list[EstadoCondicion] | None,
    rack: str | None,
    q: str | None,
    con_coordenadas: bool | None,
    solo_activos: bool,
) -> Select:
    ed = aliased(Edificio)
    pi = aliased(Piso)
    tr = aliased(Tramo)
    ti = aliased(TipoElemento)
    padre = aliased(Elemento)

    consulta = (
        consulta.join(ed, Elemento.edificio_id == ed.id)
        .join(pi, Elemento.piso_id == pi.id)
        .join(ti, Elemento.tipo_elemento_id == ti.id)
        .outerjoin(tr, Elemento.tramo_id == tr.id)
        .outerjoin(padre, Elemento.padre_id == padre.id)
    )

    if solo_activos:
        consulta = consulta.where(Elemento.activo.is_(True))
    if edificio:
        consulta = consulta.where(ed.codigo == edificio.upper())
    if piso:
        consulta = consulta.where(pi.codigo == piso.upper())
    if tramo:
        consulta = consulta.where(tr.codigo == tramo.upper())
    if tipo:
        consulta = consulta.where(ti.codigo.in_([t.upper() for t in tipo]))
    if estado:
        consulta = consulta.where(Elemento.estado_operativo.in_(estado))
    if condicion:
        consulta = consulta.where(Elemento.estado_condicion.in_(condicion))
    if rack:
        consulta = consulta.where(padre.codigo == rack.upper())
    if con_coordenadas is True:
        consulta = consulta.where(Elemento.pos_x.is_not(None), Elemento.pos_y.is_not(None))
    elif con_coordenadas is False:
        consulta = consulta.where(or_(Elemento.pos_x.is_(None), Elemento.pos_y.is_(None)))
    if q:
        patron = f"%{q.strip()}%"
        consulta = consulta.where(
            or_(
                Elemento.codigo.ilike(patron),
                Elemento.etiqueta.ilike(patron),
                Elemento.marca.ilike(patron),
                Elemento.modelo.ilike(patron),
                Elemento.numero_serie.ilike(patron),
                Elemento.direccion_ip.ilike(patron),
                Elemento.ubicacion_descriptiva.ilike(patron),
                Elemento.observaciones.ilike(patron),
            )
        )

    return consulta.order_by(pi.orden, ti.orden, Elemento.codigo)


def _exigir_marcador_propio(elemento: Elemento) -> None:
    """Un elemento montado se ubica a través de su contenedor, no por separado."""
    if elemento.montado:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"'{elemento.codigo}' está montado en '{elemento.padre_codigo}': "
            "se ubica el contenedor y el elemento se ve a través de él",
        )


def _error_de_campo(campo: str, mensaje: str) -> HTTPException:
    """422 con la forma de los errores de Pydantic, para que el visor lo
    muestre junto al campo."""
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        [{"loc": ["body", campo], "msg": mensaje, "type": "value_error"}],
    )


def _validar_numero_recinto(valor: str | None, codigo_piso: str) -> str | None:
    """El número de recinto como se guarda, o None si se dejó vacío.

    Debe ser del piso del elemento: los recintos del subterráneo empiezan con
    00, los del primer piso con 1, los del segundo con 2…
    """
    if valor is None or not valor.strip():
        return None
    numero = normalizar_numero(valor)
    if numero is None:
        raise _error_de_campo(
            "numero_recinto", "debe ser el número de la sala en el plano, como 1083 o 1083.2"
        )
    if not corresponde_al_piso(numero, codigo_piso):
        prefijo = prefijo_de_piso(codigo_piso)
        raise _error_de_campo(
            "numero_recinto",
            f"no es un recinto del piso {codigo_piso}"
            + (f": sus números empiezan con {prefijo}" if prefijo else ""),
        )
    return numero


def _cambios_de_lamina(sesion, elemento: Elemento, codigo_tramo: str | None) -> dict:
    """Cambia la lámina donde se dibuja el elemento.

    La posición guardada era sobre la lámina anterior, así que se borra: en la
    nueva no significa nada.
    """
    if elemento.montado:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"'{elemento.codigo}' está montado en '{elemento.padre_codigo}': "
            "se dibuja en la lámina de su contenedor",
        )
    tramo = obtener_tramo(sesion, elemento.piso, codigo_tramo) or elemento.tramo
    # La de su propio tramo es la lámina por omisión: se guarda como nula.
    cambios: dict = {
        "tramo_lamina_id": None if tramo is None or tramo.id == elemento.tramo_id else tramo.id
    }
    plano = elemento.plano
    if plano is not None and plano.tramo_id is not None and (tramo is None or plano.tramo_id != tramo.id):
        cambios.update(plano_id=None, pos_x=None, pos_y=None)
    return cambios


def _ordenar_hijos(hijos: list[Elemento]) -> list[Elemento]:
    """Como se ven en el rack: montados antes que conectados, de arriba hacia
    abajo según la U (se numera desde abajo) y, sin U, agrupados por tipo."""
    return sorted(
        (h for h in hijos if h.activo),
        key=lambda h: (
            not h.montado,
            h.unidad_rack is None,
            -(h.unidad_rack or 0),
            h.tipo.orden,
            h.codigo,
        ),
    )


def _armar_hijo(hijo: Elemento) -> dict:
    alto = (hijo.atributos or {}).get("unidades_rack")
    return {
        "id": hijo.id,
        "codigo": hijo.codigo,
        "etiqueta": hijo.etiqueta,
        "tipo_codigo": hijo.tipo.codigo,
        "tipo_nombre": hijo.tipo.nombre,
        "color_tipo": hijo.tipo.color,
        "estado_operativo": hijo.estado_operativo,
        "color_estado": hijo.color_estado,
        "marca": hijo.marca,
        "modelo": hijo.modelo,
        "montado": hijo.montado,
        "unidad_rack": hijo.unidad_rack,
        "alto_u": int(alto) if isinstance(alto, (int, float)) and alto > 0 else None,
    }


def _armar_detalle(elemento: Elemento) -> ElementoDetalle:
    completitud = evaluar_completitud(elemento)
    recinto = buscar_recinto(elemento)
    datos = ElementoLeer.model_validate(elemento).model_dump()
    datos.update(
        {
            "direccion_mac": elemento.direccion_mac,
            "fecha_instalacion": elemento.fecha_instalacion,
            "fecha_ultimo_levantamiento": elemento.fecha_ultimo_levantamiento,
            "observaciones": elemento.observaciones,
            "atributos": elemento.atributos or {},
            "padre_codigo": elemento.padre_codigo,
            "hijos": [_armar_hijo(h) for h in _ordenar_hijos(elemento.hijos)],
            "fotografias": [FotografiaLeer.model_validate(f) for f in elemento.fotografias],
            "externos": [IdentificadorExternoLeer.model_validate(x) for x in elemento.externos],
            "vlans": [
                {
                    "numero": ev.vlan.numero,
                    "nombre": ev.vlan.nombre,
                    "subred": ev.vlan.subred,
                    "rol": ev.rol.value,
                }
                for ev in elemento.vlans
            ],
            "completitud": CompletitudLeer(
                total_obligatorios=completitud.total_obligatorios,
                completos=completitud.completos,
                porcentaje=completitud.porcentaje,
                completo=completitud.completo,
                faltantes=completitud.faltantes,
            ),
            "recinto_en_plano": RecintoLeer.model_validate(recinto) if recinto else None,
            "creado_en": elemento.creado_en,
            "actualizado_en": elemento.actualizado_en,
        }
    )
    return ElementoDetalle(**datos)


# --------------------------------------------------------------------------
# Lectura
# --------------------------------------------------------------------------
@router.get("", response_model=PaginaElementos)
def listar_elementos(
    sesion: SesionBD,
    edificio: str | None = None,
    piso: str | None = None,
    tramo: str | None = None,
    tipo: list[str] | None = Query(default=None, description="Uno o más códigos de tipo"),
    estado: list[EstadoOperativo] | None = Query(default=None),
    condicion: list[EstadoCondicion] | None = Query(default=None),
    rack: str | None = Query(default=None, description="Código del rack contenedor"),
    q: str | None = Query(default=None, description="Búsqueda libre"),
    con_coordenadas: bool | None = None,
    solo_activos: bool = True,
    limite: int = Query(default=200, ge=1, le=1000),
    desplazamiento: int = Query(default=0, ge=0),
):
    filtros = dict(
        edificio=edificio,
        piso=piso,
        tramo=tramo,
        tipo=tipo,
        estado=estado,
        condicion=condicion,
        rack=rack,
        q=q,
        con_coordenadas=con_coordenadas,
        solo_activos=solo_activos,
    )
    consulta = _aplicar_filtros(select(Elemento), **filtros)
    total = sesion.scalar(
        select(func.count()).select_from(
            _aplicar_filtros(select(Elemento.id), **filtros).order_by(None).subquery()
        )
    )
    items = sesion.scalars(consulta.limit(limite).offset(desplazamiento)).unique().all()
    return PaginaElementos(
        total=total or 0,
        limite=limite,
        desplazamiento=desplazamiento,
        items=[ElementoLeer.model_validate(e) for e in items],
    )


@router.get("/mapa", response_model=RespuestaMapa)
def obtener_mapa(sesion: SesionBD, edificio: str, piso: str, tramo: str | None = None):
    """Plano de la vista junto con todos sus elementos.

    Sin ``tramo`` la vista es el piso completo. Con ``tramo`` muestra su
    lámina (o la del piso completo si el tramo no tiene una propia) y lo que
    está dibujado en ella, que no siempre coincide con el tramo del código:
    ver ``Elemento.tramo_lamina``.

    Devuelve también los elementos sin coordenadas, para que el visor pueda
    ofrecerlos en la bandeja de "pendientes por posicionar".
    """
    ed = obtener_edificio(sesion, edificio)
    pi = obtener_piso(sesion, ed, piso)
    tr = obtener_tramo(sesion, pi, tramo)

    consulta = select(Elemento).where(
        Elemento.edificio_id == ed.id,
        Elemento.piso_id == pi.id,
        Elemento.activo.is_(True),
    )
    elementos = sesion.scalars(consulta.order_by(Elemento.codigo)).unique().all()
    if tr is not None:
        elementos = [
            e for e in elementos if (t := e.tramo_de_lamina) is not None and t.id == tr.id
        ]

    plano = pi.plano_para(tr)

    def ubicado(elemento: Elemento) -> bool:
        # Un switch montado se ve donde está su rack; una toma, donde está
        # su punto de datos.
        elemento = elemento.representante_en_plano
        if not elemento.tiene_coordenadas:
            return False
        if plano is None:
            return True
        # Las versiones sucesivas de una lámina comparten el sistema de
        # coordenadas, así que basta con que la posición se haya fijado
        # sobre alguna versión del mismo piso–tramo.
        if elemento.plano is None:
            return plano.tramo_id is None
        return elemento.plano.piso_id == pi.id and elemento.plano.tramo_id == plano.tramo_id

    en_mapa = [
        ElementoEnMapa(**ElementoMapa.model_validate(e).model_dump(), ubicado=ubicado(e))
        for e in elementos
    ]
    return RespuestaMapa(
        edificio=ed.codigo,
        piso=pi.codigo,
        tramo=tr.codigo if tr else None,
        plano=PlanoLeer.model_validate(plano) if plano else None,
        total=len(en_mapa),
        # Solo cuentan los que llevan marcador propio: lo montado se resuelve
        # al ubicar su contenedor.
        sin_posicionar=sum(1 for e in en_mapa if not e.ubicado and not e.montado),
        elementos=en_mapa,
    )


@router.get("/{id_o_codigo}", response_model=ElementoDetalle)
def obtener_detalle(id_o_codigo: str, sesion: SesionBD):
    return _armar_detalle(obtener_elemento(sesion, id_o_codigo))


@router.put("/{id_o_codigo}/externos/{sistema}", response_model=list[IdentificadorExternoLeer])
def asignar_id_externo(
    id_o_codigo: str,
    datos: IdentificadorExternoGuardar,
    sesion: SesionBD,
    sistema: str = Path(pattern=PATRON_SISTEMA),
):
    """Registra el id del elemento en otro sistema (lo usan los conectores)."""
    elemento = obtener_elemento(sesion, id_o_codigo)
    ocupado = sesion.scalar(
        select(IdentificadorExterno).where(
            IdentificadorExterno.sistema == sistema,
            IdentificadorExterno.id_externo == datos.id_externo,
            IdentificadorExterno.elemento_id != elemento.id,
        )
    )
    if ocupado is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"El id '{datos.id_externo}' de {sistema} ya corresponde a '{ocupado.elemento.codigo}'",
        )
    actual = next((x for x in elemento.externos if x.sistema == sistema), None)
    if actual is None:
        elemento.externos.append(
            IdentificadorExterno(sistema=sistema, id_externo=datos.id_externo, url=datos.url)
        )
    else:
        actual.id_externo, actual.url = datos.id_externo, datos.url
    sesion.flush()
    return elemento.externos


@router.delete(
    "/{id_o_codigo}/externos/{sistema}", status_code=status.HTTP_204_NO_CONTENT
)
def quitar_id_externo(
    id_o_codigo: str, sesion: SesionBD, sistema: str = Path(pattern=PATRON_SISTEMA)
):
    elemento = obtener_elemento(sesion, id_o_codigo)
    actual = next((x for x in elemento.externos if x.sistema == sistema), None)
    if actual is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"'{elemento.codigo}' no tiene id en {sistema}"
        )
    elemento.externos.remove(actual)
    sesion.flush()


@router.get("/{id_o_codigo}/historial", response_model=list[HistorialLeer])
def obtener_historial(id_o_codigo: str, sesion: SesionBD, limite: int = Query(100, ge=1, le=500)):
    elemento = obtener_elemento(sesion, id_o_codigo)
    return elemento.historial[:limite]


# --------------------------------------------------------------------------
# Escritura
# --------------------------------------------------------------------------
@router.post("", response_model=ElementoDetalle, status_code=status.HTTP_201_CREATED)
def crear_elemento(datos: ElementoCrear, sesion: SesionBD, usuario: str | None = None):
    tipo = obtener_tipo(sesion, datos.tipo)
    edificio = obtener_edificio(sesion, datos.edificio)
    piso = obtener_piso(sesion, edificio, datos.piso)
    tramo = obtener_tramo(sesion, piso, datos.tramo)

    padre = None
    if datos.padre_codigo:
        padre = obtener_elemento(sesion, datos.padre_codigo)
        if not padre.tipo.es_contenedor:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"El elemento '{padre.codigo}' no es un contenedor y no puede alojar otros",
            )

    # Código: explícito o generado según la convención del SOP sección 8.
    correlativo: int | None = None
    if datos.codigo:
        codigo = datos.codigo.upper()
        try:
            correlativo = descomponer_codigo(codigo).correlativo
        except CodigoInvalido as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    else:
        if tipo.usa_correlativo:
            correlativo = siguiente_correlativo(
                sesion, edificio_id=edificio.id, tipo_elemento_id=tipo.id, piso_id=piso.id
            )
        codigo = construir_codigo(
            edificio=edificio.codigo,
            tipo=tipo.codigo,
            correlativo=correlativo,
            piso=piso.codigo,
            tramo=tramo.codigo if tramo else None,
        )

    if sesion.scalar(select(Elemento).where(Elemento.codigo == codigo)):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"El código '{codigo}' ya está en uso. Los códigos no se reutilizan (SOP 8.5).",
        )

    try:
        atributos = validar_atributos(list(tipo.atributos), datos.atributos)
    except AtributosInvalidos as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, exc.errores) from exc

    # Sin número explícito, el que trae la ubicación («Oficina 1083»).
    numero_recinto = _validar_numero_recinto(datos.numero_recinto, piso.codigo) or (
        numero_de_recinto(datos.ubicacion_descriptiva, piso.codigo)
    )

    elemento = Elemento(
        codigo=codigo,
        correlativo=correlativo,
        tipo_elemento_id=tipo.id,
        edificio_id=edificio.id,
        piso_id=piso.id,
        tramo_id=tramo.id if tramo else None,
        padre_id=padre.id if padre else None,
        atributos=atributos,
        numero_recinto=numero_recinto,
        **datos.model_dump(
            exclude={
                "codigo",
                "tipo",
                "edificio",
                "piso",
                "tramo",
                "padre_codigo",
                "atributos",
                "numero_recinto",
            }
        ),
    )
    sesion.add(elemento)
    sesion.flush()
    registrar_alta(sesion, elemento, usuario=usuario)
    # Con su recinto en las láminas, aparece ya ubicado en el plano.
    if not elemento.tiene_coordenadas and numero_recinto:
        sesion.refresh(elemento)
        ubicar_en_recinto(sesion, elemento, origen=OrigenCambio.MANUAL, usuario=usuario)
    sesion.flush()
    return _armar_detalle(elemento)


@router.patch("/{id_o_codigo}", response_model=ElementoDetalle)
def actualizar_elemento(id_o_codigo: str, datos: ElementoActualizar, sesion: SesionBD):
    """Actualización parcial con registro en bitácora.

    ``atributos`` se fusiona con la ficha existente: las claves entregadas se
    sobrescriben, el resto se conserva y una clave con valor ``null`` se
    elimina. Así el técnico puede completar la ficha por partes a medida que
    obtiene los datos en terreno.
    """
    elemento = obtener_elemento(sesion, id_o_codigo)
    entrada = datos.model_dump(exclude_unset=True, exclude={"usuario", "comentario"})
    # Borrar las coordenadas sí se permite: es lo que se hace al montarlo.
    if any(entrada.get(campo) is not None for campo in ("plano_id", "pos_x", "pos_y")):
        _exigir_marcador_propio(elemento)

    cambios: dict = {}
    # Al cambiar el número de recinto, el elemento pasa a ese recinto.
    reubicar = False
    if "numero_recinto" in entrada:
        numero = _validar_numero_recinto(entrada.pop("numero_recinto"), elemento.piso.codigo)
        cambios["numero_recinto"] = numero
        reubicar = numero is not None and numero != elemento.numero_recinto
    elif entrada.get("ubicacion_descriptiva"):
        # Una ubicación que trae su número también sirve («Sala Eléctrica
        # 2045»), salvo que el número se haya escrito aparte: ese manda.
        codigo_piso = elemento.piso.codigo
        anterior = numero_de_recinto(elemento.ubicacion_descriptiva, codigo_piso)
        numero = numero_de_recinto(entrada["ubicacion_descriptiva"], codigo_piso)
        sigue_al_texto = elemento.numero_recinto in (None, anterior)
        if numero and numero != elemento.numero_recinto and sigue_al_texto:
            cambios["numero_recinto"] = numero
            reubicar = True

    if "tramo" in entrada:
        tramo = obtener_tramo(sesion, elemento.piso, entrada.pop("tramo"))
        cambios["tramo_id"] = tramo.id if tramo else None

    if "tramo_lamina" in entrada:
        cambios.update(_cambios_de_lamina(sesion, elemento, entrada.pop("tramo_lamina")))

    if "padre_codigo" in entrada:
        codigo_padre = entrada.pop("padre_codigo")
        if codigo_padre:
            padre = obtener_elemento(sesion, codigo_padre)
            if padre.id == elemento.id:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST, "Un elemento no puede contenerse a sí mismo"
                )
            if not padre.tipo.es_contenedor:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    f"El elemento '{padre.codigo}' no es un contenedor y no puede alojar otros",
                )
            if padre.piso_id != elemento.piso_id:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    f"'{padre.codigo}' está en otro piso que '{elemento.codigo}'",
                )
            cambios["padre_id"] = padre.id
            # Al quedar montado se ve a través del rack: su posición propia
            # dejaría de dibujarse y quedaría como dato engañoso.
            montado = elemento.tipo.codigo not in TIPOS_CONECTADOS_AL_CONTENEDOR
            if montado and elemento.tiene_coordenadas:
                cambios.update(plano_id=None, pos_x=None, pos_y=None)
        else:
            cambios["padre_id"] = None

    if "atributos" in entrada:
        nuevos = entrada.pop("atributos") or {}
        fusionados = {**(elemento.atributos or {})}
        for clave, valor in nuevos.items():
            if valor is None:
                fusionados.pop(clave, None)
            else:
                fusionados[clave] = valor
        try:
            cambios["atributos"] = validar_atributos(list(elemento.tipo.atributos), fusionados)
        except AtributosInvalidos as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, exc.errores) from exc

    cambios.update(entrada)

    registrar_cambios(
        sesion,
        elemento,
        cambios,
        origen=OrigenCambio.MANUAL,
        usuario=datos.usuario,
        comentario=datos.comentario,
    )
    sesion.flush()
    # Los cambios se aplican sobre las columnas *_id; sin esto las relaciones
    # ya cargadas (tramo, lámina, contenedor) responderían con el valor anterior.
    sesion.expire(elemento)
    # Si el recinto no aparece en las láminas, conserva su posición: la ficha
    # avisa que hay que ubicarlo a mano.
    posicion_explicita = any(c in entrada for c in ("plano_id", "pos_x", "pos_y"))
    if reubicar and not posicion_explicita:
        ubicar_en_recinto(
            sesion, elemento, origen=OrigenCambio.MANUAL, usuario=datos.usuario
        )
        sesion.flush()
        sesion.expire(elemento)
    return _armar_detalle(elemento)


@router.patch("/{id_o_codigo}/posicion", response_model=ElementoDetalle)
def actualizar_posicion(id_o_codigo: str, datos: PosicionActualizar, sesion: SesionBD):
    """Guarda las coordenadas del marcador (SOP sección 10.3, punto 19)."""
    elemento = obtener_elemento(sesion, id_o_codigo)
    _exigir_marcador_propio(elemento)
    plano = next((p for p in elemento.piso.planos if p.id == datos.plano_id), None)
    if plano is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"El plano {datos.plano_id} no pertenece al piso del elemento '{elemento.codigo}'",
        )
    lamina = elemento.tramo_de_lamina
    if plano.tramo_id is not None and lamina is not None and lamina.id != plano.tramo_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"El plano {plano.id} es la lámina del tramo {plano.tramo_codigo} y "
            f"'{elemento.codigo}' se dibuja en la del tramo {lamina.codigo}",
        )
    if not (0 <= datos.pos_x <= plano.ancho_px and 0 <= datos.pos_y <= plano.alto_px):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Las coordenadas quedan fuera del plano ({plano.ancho_px}×{plano.alto_px})",
        )

    registrar_cambios(
        sesion,
        elemento,
        {"plano_id": plano.id, "pos_x": datos.pos_x, "pos_y": datos.pos_y},
        usuario=datos.usuario,
        comentario="Georreferenciación sobre el plano",
    )
    sesion.flush()
    # Lo que espera en la misma sala sin número en la lámina (el AP y la UPS
    # de una sala eléctrica) queda ahora junto a él.
    ubicar_pendientes(sesion, elemento.edificio)
    return _armar_detalle(elemento)


@router.post("/{id_o_codigo}/ubicar-en-recinto", response_model=ElementoDetalle)
def ubicar_en_su_recinto(id_o_codigo: str, sesion: SesionBD, usuario: str | None = None):
    """Lleva el elemento a su recinto: el de su número, en las láminas del piso.

    Sirve para devolverlo a su lugar después de moverlo a mano. Los puntos de
    datos quedan en el mismo punto que los demás de la sala (el visor los
    agrupa); los equipos, junto a los que ya están ahí.
    """
    elemento = obtener_elemento(sesion, id_o_codigo)
    _exigir_marcador_propio(elemento)
    if not elemento.numero_recinto:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"'{elemento.codigo}' no tiene número de recinto"
        )
    if ubicar_en_recinto(sesion, elemento, origen=OrigenCambio.MANUAL, usuario=usuario) is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"El recinto {elemento.numero_recinto} no aparece en las láminas del piso "
            f"{elemento.piso.codigo}",
        )
    ubicar_pendientes(sesion, elemento.edificio)
    sesion.flush()
    sesion.expire(elemento)
    return _armar_detalle(elemento)


@router.delete("/{id_o_codigo}", response_model=ElementoDetalle)
def dar_de_baja(
    id_o_codigo: str, sesion: SesionBD, usuario: str | None = None, motivo: str | None = None
):
    """Baja lógica: el elemento sale de la vista operativa, el código queda
    inactivo y nunca se reasigna (SOP sección 8.5)."""
    elemento = obtener_elemento(sesion, id_o_codigo)
    registrar_cambios(
        sesion,
        elemento,
        {"activo": False, "estado_operativo": EstadoOperativo.RETIRADO},
        usuario=usuario,
        comentario=motivo or "Baja del elemento",
    )
    sesion.flush()
    return _armar_detalle(elemento)


@router.post(
    "/{id_o_codigo}/fotografias",
    response_model=FotografiaLeer,
    status_code=status.HTTP_201_CREATED,
)
def cargar_fotografia(
    id_o_codigo: str,
    sesion: SesionBD,
    archivo: UploadFile = File(...),
    descripcion: str | None = Form(None),
    tomada_en: dt.datetime | None = Form(None),
):
    """Evidencia fotográfica. Se almacena como ``<código>_<n>.<ext>``
    siguiendo la nomenclatura del SOP sección 10.4."""
    elemento = obtener_elemento(sesion, id_o_codigo)
    try:
        return guardar_fotografia(
            sesion,
            elemento,
            _nombre_seguro(archivo.filename or "foto.jpg"),
            archivo.file.read(),
            descripcion=descripcion,
            tomada_en=tomada_en,
        )
    except FormatoFotoNoAdmitido as exc:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(exc)) from exc


@router.post("/{id_o_codigo}/vlans", response_model=ElementoDetalle)
def asignar_vlan(id_o_codigo: str, datos: VlanAsignar, sesion: SesionBD):
    elemento = obtener_elemento(sesion, id_o_codigo)
    vlan = sesion.get(Vlan, datos.vlan_id)
    if vlan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No existe la VLAN {datos.vlan_id}")

    ya_asignada = any(ev.vlan_id == vlan.id and ev.rol == datos.rol for ev in elemento.vlans)
    if not ya_asignada:
        sesion.add(ElementoVlan(elemento_id=elemento.id, vlan_id=vlan.id, rol=datos.rol))
        sesion.flush()
        sesion.refresh(elemento)
    return _armar_detalle(elemento)
