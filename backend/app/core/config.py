"""Configuración de la aplicación.

Todos los valores pueden sobrescribirse con variables de entorno con el
prefijo ``NETDOC_`` o desde un archivo ``.env`` en la raíz del repositorio.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py -> backend/
DIR_BACKEND = Path(__file__).resolve().parents[2]
DIR_PROYECTO = DIR_BACKEND.parent


class UsuarioAdicional(BaseModel):
    """Otro usuario, además del administrador (``app.scripts.usuarios``)."""

    #: Hash Argon2id de su contraseña.
    clave_hash: str
    #: Código del único edificio que puede ver y modificar; nulo, todos.
    edificio: str | None = None


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

    #: Carpeta donde se almacenan planos y fotografías de evidencia.
    dir_media: Path = DIR_BACKEND / "media"

    #: Visor compilado (npm run build). La API lo sirve en la raíz, para que el
    #: navegador hable con un solo origen.
    dir_visor: Path = DIR_PROYECTO / "frontend" / "dist"

    #: Tamaño máximo de un plano o fotografía que se carga por la API.
    carga_max_mb: int = 100

    #: Pre-dibujar las láminas en teselas para que el visor se mueva con
    #: fluidez (app.servicios.teselas). Toma ~1 GB de memoria por unos segundos
    #: con las láminas grandes; sin ellas, el visor muestra la lámina original.
    teselas: bool = True

    # --- Acceso (app.servicios.autenticacion) ------------------------------
    #: Administrador principal.
    admin_usuario: str = "admin-netdoc"
    #: Hash Argon2id de su contraseña. No tiene valor por omisión: vive en .env,
    #: fuera del repositorio (python -m app.scripts.definir_clave), y sin él
    #: nadie puede ingresar.
    admin_clave_hash: str = ""
    #: Los demás usuarios, por nombre. También viven en .env, como JSON: los
    #: escribe python -m app.scripts.usuarios.
    usuarios: dict[str, UsuarioAdicional] = {}
    #: Intentos fallidos que admite un mismo equipo antes de bloquearlo…
    ingreso_intentos: int = 3
    #: …y entre todos los equipos, contra un ataque repartido entre muchos.
    ingreso_intentos_globales: int = 30
    #: Minutos que cuenta un intento fallido: con el límite alcanzado, lo que
    #: hay que esperar para volver a intentar.
    ingreso_bloqueo_minutos: int = 15
    #: Duración máxima de una sesión, aunque se esté usando…
    sesion_horas: int = 12
    #: …y lo que dura sin actividad.
    sesion_inactividad_minutos: int = 30

    #: Token compartido con los sistemas que no pueden iniciar sesión: los
    #: webhooks de monitoreo (Zabbix, Alertmanager) y quienes leen el inventario
    #: (Prometheus, NetBox, GLPI). Vacío deshabilita ese acceso.
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
