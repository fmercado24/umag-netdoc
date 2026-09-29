"""Configuración de la aplicación.

Todos los valores pueden sobrescribirse con variables de entorno con el
prefijo ``NETDOC_`` o desde un archivo ``.env`` en la raíz del repositorio.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py -> backend/
DIR_BACKEND = Path(__file__).resolve().parents[2]
DIR_PROYECTO = DIR_BACKEND.parent


class Configuracion(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NETDOC_",
        env_file=(DIR_PROYECTO / ".env", DIR_BACKEND / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    nombre_app: str = "Sistema de documentación visual de infraestructura de red — UMAG"
    version: str = "0.1.0"
    entorno: str = "desarrollo"

    #: URL de conexión SQLAlchemy. SQLite por defecto para poder trabajar sin
    #: servicios externos; el modelo es compatible con PostgreSQL sin cambios.
    database_url: str = f"sqlite:///{DIR_BACKEND / 'umag_netdoc.db'}"

    #: Orígenes autorizados para CORS, separados por coma.
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    #: Carpeta donde se almacenan planos y fotografías de evidencia.
    dir_media: Path = DIR_BACKEND / "media"

    #: Token compartido con la herramienta de monitoreo (Zabbix). Vacío
    #: deshabilita el endpoint de sincronización automática de estado.
    monitoreo_token: str = ""

    #: Minutos que un elemento debe permanecer caído antes de marcarse
    #: "en falla" (SOP-DSI-RED-001, sección 11.3).
    monitoreo_minutos_falla: int = 10

    # --- Conector con Zabbix (app.scripts.sincronizar zabbix) --------------
    #: URL de la API, p. ej. https://zabbix.umag.cl/api_jsonrpc.php
    zabbix_url: str = ""
    #: Token de API de Zabbix (Usuarios → Tokens de API). Requiere Zabbix 6.4+.
    zabbix_token: str = ""
    #: Grupo bajo el que se crean los de edificio y piso: NetDoc/CADI/P01.
    zabbix_grupo_raiz: str = "NetDoc"
    #: Tipos que se llevan a Zabbix (los que tienen IP de gestión que vigilar).
    zabbix_tipos: str = "SW,RT,AP,UPS,SV,PBX,ONT,MC"
    #: Plantillas que se asignan a los hosts nuevos, separadas por coma.
    zabbix_plantillas: str = ""
    #: Comunidad SNMP de la interfaz de los hosts nuevos (admite una macro).
    zabbix_comunidad_snmp: str = "{$SNMP_COMMUNITY}"

    @property
    def lista_cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def dir_planos(self) -> Path:
        return self.dir_media / "planos"

    @property
    def dir_fotografias(self) -> Path:
        return self.dir_media / "fotografias"

    @property
    def es_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def obtener_configuracion() -> Configuracion:
    cfg = Configuracion()
    cfg.dir_planos.mkdir(parents=True, exist_ok=True)
    cfg.dir_fotografias.mkdir(parents=True, exist_ok=True)
    return cfg


configuracion = obtener_configuracion()
