"""Inventario en un formato estable para otros sistemas.

``netdoc.inventario/v1`` es un contrato: los conectores (NetBox, GLPI,
Zabbix…) y cualquier script externo pueden depender de estos nombres. Si hay
que cambiarlos, se publica una ``v2`` y se mantiene la ``v1`` mientras alguien
la use. Los nombres internos de la base pueden cambiar sin romper a nadie.
"""

from __future__ import annotations

import csv
import io
import json

from app.models import Elemento
from app.servicios.validacion import evaluar_completitud

ESQUEMA = "netdoc.inventario/v1"


def a_registro(e: Elemento) -> dict:
    """Un elemento como registro de inventario ``v1``."""
    return {
        "codigo": e.codigo,
        "tipo": {"codigo": e.tipo.codigo, "nombre": e.tipo.nombre, "categoria": e.categoria},
        "etiqueta": e.etiqueta,
        "activo": e.activo,
        "estado_operativo": e.estado_operativo.value,
        "estado_condicion": e.estado_condicion.value if e.estado_condicion else None,
        "criticidad": e.criticidad.value if e.criticidad else None,
        "ubicacion": {
            "edificio": e.edificio.codigo,
            "piso": e.piso.codigo,
            "tramo": e.tramo_codigo,
            "lamina": e.tramo_lamina_codigo,
            "recinto": e.ubicacion_descriptiva,
            # Un switch montado en un rack está donde está el rack.
            "contenedor": e.padre_codigo,
            "montado": e.montado,
            "unidad_rack": e.unidad_rack,
            "plano_id": e.representante_en_plano.plano_id,
            "x": e.representante_en_plano.pos_x,
            "y": e.representante_en_plano.pos_y,
        },
        "red": {"direccion_ip": e.direccion_ip, "direccion_mac": e.direccion_mac},
        "equipo": {"marca": e.marca, "modelo": e.modelo, "numero_serie": e.numero_serie},
        "fechas": {
            "instalacion": e.fecha_instalacion.isoformat() if e.fecha_instalacion else None,
            "ultimo_levantamiento": (
                e.fecha_ultimo_levantamiento.isoformat() if e.fecha_ultimo_levantamiento else None
            ),
            "creado_en": e.creado_en.isoformat(),
            "actualizado_en": e.actualizado_en.isoformat(),
        },
        "atributos": e.atributos or {},
        "completitud": evaluar_completitud(e).porcentaje,
        "externos": {x.sistema: {"id": x.id_externo, "url": x.url} for x in e.externos},
    }


#: Columnas del CSV: el registro aplanado, con los grupos como prefijo.
COLUMNAS_CSV = [
    "codigo",
    "tipo",
    "tipo_nombre",
    "categoria",
    "etiqueta",
    "activo",
    "estado_operativo",
    "estado_condicion",
    "criticidad",
    "edificio",
    "piso",
    "tramo",
    "lamina",
    "recinto",
    "contenedor",
    "montado",
    "unidad_rack",
    "plano_id",
    "x",
    "y",
    "direccion_ip",
    "direccion_mac",
    "marca",
    "modelo",
    "numero_serie",
    "fecha_instalacion",
    "fecha_ultimo_levantamiento",
    "creado_en",
    "actualizado_en",
    "completitud",
    "atributos",
    "externos",
]


def a_fila_csv(registro: dict) -> dict:
    """Aplana un registro ``v1``; atributos y externos van como JSON."""
    return {
        "codigo": registro["codigo"],
        "tipo": registro["tipo"]["codigo"],
        "tipo_nombre": registro["tipo"]["nombre"],
        "categoria": registro["tipo"]["categoria"],
        "etiqueta": registro["etiqueta"],
        "activo": registro["activo"],
        "estado_operativo": registro["estado_operativo"],
        "estado_condicion": registro["estado_condicion"],
        "criticidad": registro["criticidad"],
        **registro["ubicacion"],
        **registro["red"],
        **registro["equipo"],
        "fecha_instalacion": registro["fechas"]["instalacion"],
        "fecha_ultimo_levantamiento": registro["fechas"]["ultimo_levantamiento"],
        "creado_en": registro["fechas"]["creado_en"],
        "actualizado_en": registro["fechas"]["actualizado_en"],
        "completitud": registro["completitud"],
        "atributos": json.dumps(registro["atributos"], ensure_ascii=False, sort_keys=True),
        "externos": json.dumps(
            {sistema: dato["id"] for sistema, dato in registro["externos"].items()},
            ensure_ascii=False,
            sort_keys=True,
        ),
    }


def a_csv(registros: list[dict]) -> str:
    salida = io.StringIO()
    escritor = csv.DictWriter(salida, fieldnames=COLUMNAS_CSV, extrasaction="raise")
    escritor.writeheader()
    for registro in registros:
        escritor.writerow(a_fila_csv(registro))
    return salida.getvalue()
