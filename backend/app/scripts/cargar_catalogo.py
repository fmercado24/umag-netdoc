"""Carga el catálogo base: edificios, tipos de elemento y fichas.

    python -m app.scripts.cargar_catalogo

Es idempotente: se puede ejecutar cuantas veces se quiera. Los edificios y
tipos existentes no se tocan; a los tipos ya cargados solo se les agregan las
definiciones de atributo que falten.

Fuente: SOP-DSI-RED-001, secciones 7 (taxonomía), 8.2 (edificios),
8.4 (códigos de tipo) y 9.2 (fichas por tipo).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import SesionLocal
from app.models import (
    CategoriaElemento,
    DefinicionAtributo,
    Edificio,
    TipoDato,
    TipoElemento,
)

# --------------------------------------------------------------------------
# Edificios (SOP sección 8.2)
# --------------------------------------------------------------------------
EDIFICIOS: list[tuple[str, str]] = [
    ("ING", "Edificio Facultad de Ingeniería"),
    ("DSI", "Edificio Dirección de Servicios Informáticos"),
    ("CADI", "Campus Asistencial Docente e Investigación"),
    ("HUM", "Edificio Facultad de Educación y Cs. Sociales / Cs. Económicas y Jurídicas"),
    ("SAL", "Edificio Facultad de Ciencias de la Salud / Escuela de Medicina"),
    ("CS", "Edificio Facultad de Ciencias"),
    ("GIM", "Gimnasio Universitario"),
    ("AGR", "Edificio Facultad de Cs. Agropecuarias y Agrícolas"),
    ("PED", "Edificio Pabellón de Pedagogías"),
    ("DEC", "Edificio Decanato Facultad de Educación y Ciencias Sociales"),
    ("CAS", "Edificio Casino Universitario"),
    ("BIB", "Edificio Biblioteca y American Corner"),
    ("PLA", "Edificio Planificación y Desarrollo Institucional"),
    ("FEUM", "Edificio Dirección de Bienestar y Desarrollo Estudiantil / FEUMAG"),
    ("VRAF", "Edificio Vicerrectoría de Administración y Finanzas"),
    ("REC", "Edificio Rectoría"),
    ("CIGA", "Edificio Centro de Investigación GAIA Antártica"),
    ("CERE", "Edificio Centro de Estudio de los Recursos Energéticos"),
    ("PAT", "Edificio Instituto de la Patagonia"),
]

# --------------------------------------------------------------------------
# Tipos de elemento y sus fichas (SOP secciones 7.2, 8.4 y 9.2)
#
# Cada atributo es: (clave, etiqueta, tipo_dato, obligatorio, opciones, unidad)
# Los atributos comunes de la sección 9.1 (marca, modelo, serie, MAC, IP,
# fechas, responsable…) son columnas del elemento y no se repiten aquí.
# --------------------------------------------------------------------------
Atributo = tuple[str, str, TipoDato, bool, list | None, str | None]

CATEGORIAS_CABLE = ["Cat5e", "Cat6", "Cat6A", "Fibra"]

TIPOS: list[dict] = [
    {
        "codigo": "SW",
        "nombre": "Switch",
        "categoria": CategoriaElemento.ACTIVO,
        "icono": "switch",
        "color": "#2563EB",
        "orden": 10,
        "atributos": [
            ("vlan_gestion", "VLAN de gestión", TipoDato.NUMERO, True, None, None),
            ("puertos_totales", "N° de puertos totales", TipoDato.NUMERO, True, None, None),
            ("puertos_ocupados", "N° de puertos ocupados", TipoDato.NUMERO, True, None, None),
            ("uplink", "Puerto de uplink y switch al que conecta", TipoDato.REFERENCIA, True, None, None),
            ("version_firmware", "Versión de firmware", TipoDato.TEXTO, False, None, None),
            ("poe", "PoE disponible", TipoDato.BOOLEANO, False, None, None),
            ("capa", "Capa", TipoDato.ENUM, False, ["acceso", "distribucion", "nucleo"], None),
        ],
    },
    {
        "codigo": "RT",
        "nombre": "Router",
        "categoria": CategoriaElemento.ACTIVO,
        "icono": "router",
        "color": "#7C3AED",
        "orden": 20,
        "atributos": [
            ("proveedor", "Proveedor del enlace", TipoDato.TEXTO, False, None, None),
            ("identificador_servicio", "Identificador del servicio contratado", TipoDato.TEXTO, False, None, None),
            ("interfaces_wan", "Interfaces WAN", TipoDato.LISTA, False, None, None),
            ("version_firmware", "Versión de firmware", TipoDato.TEXTO, False, None, None),
        ],
    },
    {
        "codigo": "AP",
        "nombre": "Access Point",
        "categoria": CategoriaElemento.ACTIVO,
        "icono": "wifi",
        "color": "#0891B2",
        "orden": 30,
        "atributos": [
            ("ssids", "SSIDs difundidos", TipoDato.LISTA, True, None, None),
            ("bandas", "Bandas soportadas", TipoDato.LISTA, True, None, None),
            ("switch_origen", "Switch y puerto de origen", TipoDato.REFERENCIA, True, None, None),
            ("controladora", "Controladora", TipoDato.TEXTO, False, None, None),
        ],
    },
    {
        "codigo": "MC",
        "nombre": "Media converter",
        "categoria": CategoriaElemento.ACTIVO,
        "icono": "conversor",
        "color": "#059669",
        "orden": 40,
        "atributos": [
            ("interfaz_cobre", "Interfaz lado cobre", TipoDato.ENUM, True,
             ["100BASE-TX", "1000BASE-T", "10GBASE-T"], None),
            ("interfaz_fibra", "Interfaz lado fibra", TipoDato.TEXTO, True, None, None),
            ("enlace_remoto", "Enlace remoto", TipoDato.REFERENCIA, True, None, None),
            ("alimentacion", "Alimentación", TipoDato.TEXTO, True, None, None),
        ],
    },
    {
        "codigo": "ONT",
        "nombre": "Optical Network Terminal",
        "categoria": CategoriaElemento.ACTIVO,
        "icono": "conversor",
        "color": "#0D9488",
        "orden": 50,
        "atributos": [
            ("interfaz_cobre", "Interfaz lado cobre", TipoDato.ENUM, True,
             ["100BASE-TX", "1000BASE-T", "10GBASE-T"], None),
            ("interfaz_fibra", "Interfaz lado fibra", TipoDato.TEXTO, True, None, None),
            ("enlace_remoto", "Enlace remoto", TipoDato.REFERENCIA, True, None, None),
            ("alimentacion", "Alimentación", TipoDato.TEXTO, True, None, None),
        ],
    },
    {
        "codigo": "PBX",
        "nombre": "Central telefónica",
        "categoria": CategoriaElemento.ACTIVO,
        "icono": "telefono",
        "color": "#9333EA",
        "orden": 60,
        "atributos": [
            ("anexos_configurados", "Anexos configurados", TipoDato.NUMERO, False, None, None),
            ("troncal_sip", "Troncal SIP", TipoDato.TEXTO, False, None, None),
            ("unidades_rack", "Unidades de rack ocupadas", TipoDato.NUMERO, False, None, "U"),
        ],
    },
    {
        "codigo": "SV",
        "nombre": "Servidor",
        "categoria": CategoriaElemento.ACTIVO,
        "icono": "servidor",
        "color": "#4F46E5",
        "orden": 70,
        "atributos": [
            ("sistema_operativo", "Sistema operativo", TipoDato.TEXTO, False, None, None),
            ("servicios", "Servicios que presta", TipoDato.LISTA, False, None, None),
            ("unidades_rack", "Unidades de rack ocupadas", TipoDato.NUMERO, False, None, "U"),
        ],
    },
    {
        "codigo": "PP",
        "nombre": "Patch panel",
        "categoria": CategoriaElemento.PASIVO,
        "icono": "patch-panel",
        "color": "#D97706",
        "orden": 100,
        "atributos": [
            ("puertos_totales", "N° de puertos totales", TipoDato.NUMERO, True, None, None),
            ("puertos_ocupados", "N° de puertos ocupados", TipoDato.NUMERO, True, None, None),
            ("categoria_cableado", "Categoría de cableado", TipoDato.ENUM, True, CATEGORIAS_CABLE, None),
            ("unidades_rack", "Unidades de rack ocupadas", TipoDato.NUMERO, True, None, "U"),
            ("mapeo_documentado", "Mapeo puerto → punto de datos documentado",
             TipoDato.BOOLEANO, False, None, None),
        ],
    },
    {
        "codigo": "ODF",
        "nombre": "Distribuidor de fibra (cabecera F.O.)",
        "categoria": CategoriaElemento.PASIVO,
        "icono": "fibra",
        "color": "#EA580C",
        "orden": 110,
        "atributos": [
            ("hilos_totales", "Hilos totales", TipoDato.NUMERO, True, None, None),
            ("hilos_ocupados", "Hilos ocupados", TipoDato.NUMERO, True, None, None),
            ("tipo_fibra", "Tipo de fibra", TipoDato.ENUM, True, ["monomodo", "multimodo"], None),
            ("tipo_conector", "Tipo de conector", TipoDato.ENUM, True, ["SC", "LC", "ST", "FC"], None),
            ("enlace_remoto", "Enlace remoto", TipoDato.REFERENCIA, False, None, None),
        ],
    },
    {
        "codigo": "PD",
        "nombre": "Punto de datos",
        "categoria": CategoriaElemento.PASIVO,
        "icono": "toma",
        "color": "#CA8A04",
        "orden": 120,
        "usa_correlativo": False,
        "atributos": [
            ("puerto_origen", "Puerto en el patch panel de origen", TipoDato.REFERENCIA, True, None, None),
            ("vlan_por_defecto", "VLAN por defecto", TipoDato.NUMERO, True, None, None),
            ("categoria_cable", "Categoría del cable", TipoDato.ENUM, True, CATEGORIAS_CABLE, None),
            ("certificado", "Certificado", TipoDato.BOOLEANO, True, None, None),
            ("fecha_certificacion", "Fecha de certificación", TipoDato.FECHA, False, None, None),
            ("estado_puerto", "Estado del puerto", TipoDato.ENUM, True,
             ["habilitado", "deshabilitado", "reservado"], None),
            # Extensión sobre el mínimo del SOP §9.2.4: el prefijo del rótulo
            # físico (D/T/C…) identifica el servicio que presta la toma.
            ("servicio", "Servicio", TipoDato.ENUM, False,
             ["datos", "telefonia", "cctv", "video", "impresion", "otro"], None),
        ],
    },
    {
        "codigo": "R",
        "nombre": "Rack",
        "categoria": CategoriaElemento.SOPORTE,
        "icono": "rack",
        "color": "#475569",
        "orden": 200,
        "es_contenedor": True,
        "atributos": [
            ("tipo_rack", "Tipo", TipoDato.ENUM, True, ["cerrado", "abierto", "mural"], None),
            ("unidades_totales", "Unidades totales", TipoDato.NUMERO, False, None, "U"),
            ("unidades_ocupadas", "U ocupadas", TipoDato.NUMERO, True, None, "U"),
            ("alimentacion_electrica", "Alimentación eléctrica (circuito, UPS asociado)",
             TipoDato.TEXTO, True, None, None),
            ("ventilacion", "Ventilación", TipoDato.BOOLEANO, False, None, None),
        ],
    },
    {
        "codigo": "UPS",
        "nombre": "UPS",
        "categoria": CategoriaElemento.SOPORTE,
        "icono": "ups",
        "color": "#DC2626",
        "orden": 210,
        "atributos": [
            ("capacidad_va", "Capacidad", TipoDato.NUMERO, True, None, "VA"),
            ("capacidad_w", "Potencia", TipoDato.NUMERO, False, None, "W"),
            ("autonomia_min", "Autonomía estimada", TipoDato.NUMERO, True, None, "min"),
            ("cargas_conectadas", "Cargas conectadas", TipoDato.LISTA, True, None, None),
            ("fecha_cambio_baterias", "Fecha de último cambio de baterías", TipoDato.FECHA, True, None, None),
        ],
    },
    {
        "codigo": "PDU",
        "nombre": "PDU",
        "categoria": CategoriaElemento.SOPORTE,
        "icono": "pdu",
        "color": "#B91C1C",
        "orden": 220,
        "atributos": [
            ("numero_tomas", "N° de tomas", TipoDato.NUMERO, True, None, None),
            ("amperaje", "Amperaje", TipoDato.NUMERO, False, None, "A"),
            ("gestionable", "Gestionable por red", TipoDato.BOOLEANO, False, None, None),
        ],
    },
]


def cargar_edificios(sesion: Session) -> int:
    creados = 0
    for codigo, nombre in EDIFICIOS:
        if sesion.scalar(select(Edificio).where(Edificio.codigo == codigo)):
            continue
        sesion.add(Edificio(codigo=codigo, nombre=nombre, campus="Punta Arenas"))
        creados += 1
    return creados


def cargar_tipos(sesion: Session) -> tuple[int, int]:
    tipos_creados = 0
    atributos_creados = 0

    for definicion in TIPOS:
        atributos: list[Atributo] = definicion["atributos"]
        tipo = sesion.scalar(
            select(TipoElemento).where(TipoElemento.codigo == definicion["codigo"])
        )

        if tipo is None:
            tipo = TipoElemento(
                codigo=definicion["codigo"],
                nombre=definicion["nombre"],
                categoria=definicion["categoria"],
                icono=definicion.get("icono"),
                color=definicion.get("color"),
                orden=definicion.get("orden", 0),
                es_contenedor=definicion.get("es_contenedor", False),
                usa_correlativo=definicion.get("usa_correlativo", True),
            )
            sesion.add(tipo)
            sesion.flush()
            tipos_creados += 1

        existentes = {a.clave for a in tipo.atributos}
        for orden, (clave, etiqueta, tipo_dato, obligatorio, opciones, unidad) in enumerate(
            atributos, start=1
        ):
            if clave in existentes:
                continue
            sesion.add(
                DefinicionAtributo(
                    tipo_elemento_id=tipo.id,
                    clave=clave,
                    etiqueta=etiqueta,
                    tipo_dato=tipo_dato,
                    obligatorio=obligatorio,
                    opciones=opciones,
                    unidad=unidad,
                    orden=orden * 10,
                )
            )
            atributos_creados += 1

    return tipos_creados, atributos_creados


def main() -> None:
    with SesionLocal() as sesion:
        edificios = cargar_edificios(sesion)
        tipos, atributos = cargar_tipos(sesion)
        sesion.commit()

    print(f"Edificios creados: {edificios}")
    print(f"Tipos de elemento creados: {tipos}")
    print(f"Definiciones de atributo creadas: {atributos}")


if __name__ == "__main__":
    main()
