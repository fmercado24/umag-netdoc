"""Enumeraciones controladas del dominio.

Los valores provienen de SOP-DSI-RED-001 (secciones 7, 9.1 y 11.3). Se usan
identificadores en minúscula y sin tilde como valor almacenado, y la etiqueta
legible se resuelve en la capa de presentación.
"""

from __future__ import annotations

from enum import Enum


class CategoriaElemento(str, Enum):
    """SOP sección 7.1."""

    ACTIVO = "activo"        # switches, routers, access points
    PASIVO = "pasivo"        # patch panels, puntos de datos, faceplates
    SOPORTE = "soporte"      # racks, UPS, PDU
    LOGICO = "logico"        # VLAN, subred, SSID


class EstadoOperativo(str, Enum):
    """SOP sección 9.1. Se sincroniza con monitoreo (sección 11.3)."""

    ACTIVO = "activo"
    INACTIVO = "inactivo"
    EN_FALLA = "en_falla"
    EN_MANTENIMIENTO = "en_mantenimiento"
    RETIRADO = "retirado"


class EstadoCondicion(str, Enum):
    """SOP sección 9.1."""

    EXCELENTE = "excelente"
    REGULAR = "regular"
    MALO = "malo"
    OBSOLETO = "obsoleto"


class Criticidad(str, Enum):
    """Nivel de criticidad del elemento (propuesta de memoria, sección 4.1)."""

    ALTA = "alta"
    MEDIA = "media"
    BAJA = "baja"


class TipoDato(str, Enum):
    """Tipos admitidos para los atributos de ficha definidos por catálogo."""

    TEXTO = "texto"
    NUMERO = "numero"
    BOOLEANO = "booleano"
    FECHA = "fecha"
    ENUM = "enum"
    IP = "ip"
    MAC = "mac"
    LISTA = "lista"
    REFERENCIA = "referencia"  # código de otro elemento


class OrigenCambio(str, Enum):
    """Quién originó una entrada del historial del elemento."""

    MANUAL = "manual"
    MONITOREO = "monitoreo"
    IMPORTACION = "importacion"
    SISTEMA = "sistema"


class MedioEnlace(str, Enum):
    COBRE = "cobre"
    FIBRA = "fibra"
    INALAMBRICO = "inalambrico"


class RolVlan(str, Enum):
    GESTION = "gestion"
    SERVICIO = "servicio"
    ACCESO = "acceso"


class EstadoLevantamiento(str, Enum):
    EN_CURSO = "en_curso"
    CERRADO = "cerrado"


#: Etiquetas legibles para la interfaz y los reportes.
ETIQUETAS: dict[str, dict[str, str]] = {
    "estado_operativo": {
        EstadoOperativo.ACTIVO: "Activo / En línea",
        EstadoOperativo.INACTIVO: "Inactivo / Fuera de línea",
        EstadoOperativo.EN_FALLA: "En falla",
        EstadoOperativo.EN_MANTENIMIENTO: "En mantenimiento",
        EstadoOperativo.RETIRADO: "Retirado",
    },
    "estado_condicion": {
        EstadoCondicion.EXCELENTE: "Excelente / Bueno (óptimo)",
        EstadoCondicion.REGULAR: "Regular / Aceptable",
        EstadoCondicion.MALO: "Malo / Crítico",
        EstadoCondicion.OBSOLETO: "Obsoleto",
    },
    "categoria": {
        CategoriaElemento.ACTIVO: "Equipos activos de red",
        CategoriaElemento.PASIVO: "Elementos pasivos de cableado",
        CategoriaElemento.SOPORTE: "Infraestructura de soporte",
        CategoriaElemento.LOGICO: "Elementos lógicos asociados",
    },
}

#: Color asociado a cada estado operativo, usado por los marcadores del plano.
COLORES_ESTADO: dict[str, str] = {
    EstadoOperativo.ACTIVO: "#1B9E5A",
    EstadoOperativo.INACTIVO: "#6B7280",
    EstadoOperativo.EN_FALLA: "#D92D20",
    EstadoOperativo.EN_MANTENIMIENTO: "#D97706",
    EstadoOperativo.RETIRADO: "#3F3F46",
}
