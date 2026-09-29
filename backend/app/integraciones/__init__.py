"""Conectores con sistemas externos. Ver ``app.integraciones.base``."""

from app.integraciones.base import Accion, Conector, ErrorConector
from app.integraciones.zabbix import ConectorZabbix

#: Sistema → cómo construir su conector a partir de la configuración.
CONECTORES = {
    "zabbix": ConectorZabbix.desde_configuracion,
}

__all__ = ["CONECTORES", "Accion", "Conector", "ConectorZabbix", "ErrorConector"]
