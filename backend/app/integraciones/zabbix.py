"""Conector con Zabbix: los elementos con IP de gestión como hosts.

Cada elemento es un host cuyo nombre técnico es su código (``CADI-SW01-P01-T2``),
que nunca cambia (SOP §8.5), así que la próxima pasada lo reconoce. NetDoc
administra solo lo suyo: los grupos bajo ``NETDOC_ZABBIX_GRUPO_RAIZ``
(``NetDoc/CADI``, ``NetDoc/CADI/P01``) y las etiquetas ``netdoc_*``. Los demás
grupos, etiquetas, plantillas e interfaces que el equipo de monitoreo agregue
en Zabbix se conservan. La interfaz y las plantillas solo se fijan al crear el
host.

El camino de vuelta ya existe: el webhook de ``deploy/zabbix`` informa a
NetDoc los problemas de estos hosts, identificándolos por el mismo código.

Usa la API JSON-RPC con token en la cabecera ``Authorization`` (Zabbix 6.4 o
posterior).
"""

from __future__ import annotations

import itertools
import json
import urllib.error
import urllib.request

from app.core.config import configuracion
from app.integraciones.base import Accion, Conector, ErrorConector
from app.models import Elemento, EstadoOperativo

PREFIJO_ETIQUETA = "netdoc_"


class ClienteZabbix:
    """Llamadas a ``api_jsonrpc.php``."""

    def __init__(self, url: str, token: str, tiempo_espera: float = 15) -> None:
        self.url = url
        self.token = token
        self.tiempo_espera = tiempo_espera
        self._ids = itertools.count(1)

    def llamar(self, metodo: str, parametros: dict | list) -> object:
        cuerpo = json.dumps(
            {"jsonrpc": "2.0", "method": metodo, "params": parametros, "id": next(self._ids)}
        ).encode()
        peticion = urllib.request.Request(
            self.url,
            data=cuerpo,
            headers={
                "Content-Type": "application/json-rpc",
                "Authorization": f"Bearer {self.token}",
            },
        )
        try:
            with urllib.request.urlopen(peticion, timeout=self.tiempo_espera) as respuesta:
                datos = json.load(respuesta)
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ErrorConector(f"Zabbix no respondió en {self.url}: {exc}") from exc
        if "error" in datos:
            error = datos["error"]
            raise ErrorConector(f"Zabbix rechazó {metodo}: {error.get('message')} {error.get('data', '')}")
        return datos["result"]


class ConectorZabbix(Conector):
    sistema = "zabbix"

    def __init__(
        self,
        cliente: ClienteZabbix,
        *,
        grupo_raiz: str = "NetDoc",
        tipos: set[str] | None = None,
        plantillas: list[str] | None = None,
        comunidad_snmp: str = "{$SNMP_COMMUNITY}",
    ) -> None:
        self.cliente = cliente
        self.grupo_raiz = grupo_raiz
        self.tipos = tipos
        self.plantillas = plantillas or []
        self.comunidad_snmp = comunidad_snmp
        self._grupos: dict[str, str] = {}

    @classmethod
    def desde_configuracion(cls) -> ConectorZabbix:
        if not configuracion.zabbix_url or not configuracion.zabbix_token:
            raise ErrorConector("Defina NETDOC_ZABBIX_URL y NETDOC_ZABBIX_TOKEN para usar Zabbix")
        return cls(
            ClienteZabbix(configuracion.zabbix_url, configuracion.zabbix_token),
            grupo_raiz=configuracion.zabbix_grupo_raiz,
            tipos={t.strip().upper() for t in configuracion.zabbix_tipos.split(",") if t.strip()},
            plantillas=[p.strip() for p in configuracion.zabbix_plantillas.split(",") if p.strip()],
            comunidad_snmp=configuracion.zabbix_comunidad_snmp,
        )

    # --- Qué se lleva ------------------------------------------------------
    def seleccionar(self, elementos: list[Elemento]) -> list[Elemento]:
        return [
            e
            for e in elementos
            if e.activo
            and e.direccion_ip
            and e.estado_operativo is not EstadoOperativo.RETIRADO
            and (self.tipos is None or e.tipo.codigo in self.tipos)
        ]

    def _propio(self, elemento: Elemento) -> dict:
        """Lo que NetDoc administra del host."""
        edificio = f"{self.grupo_raiz}/{elemento.edificio.codigo}"
        etiquetas = {
            "netdoc_codigo": elemento.codigo,
            "netdoc_tipo": elemento.tipo.codigo,
            "netdoc_piso": elemento.piso.codigo,
            "netdoc_tramo": elemento.tramo_codigo,
            "netdoc_criticidad": elemento.criticidad.value if elemento.criticidad else None,
        }
        return {
            "name": f"{elemento.codigo} {elemento.etiqueta}" if elemento.etiqueta else elemento.codigo,
            "grupos": sorted({edificio, f"{edificio}/{elemento.piso.codigo}"}),
            "tags": sorted(
                ({"tag": k, "value": v} for k, v in etiquetas.items() if v),
                key=lambda t: t["tag"],
            ),
        }

    # --- Plan ---------------------------------------------------------------
    def planificar(self, elementos: list[Elemento]) -> list[Accion]:
        existentes = {
            h["host"]: h
            for h in self.cliente.llamar(
                "host.get",
                {
                    "output": ["hostid", "host", "name"],
                    "filter": {"host": [e.codigo for e in elementos]},
                    "selectHostGroups": ["name"],
                    "selectTags": ["tag", "value"],
                },
            )
        } if elementos else {}

        # El host se llama como el código, que cambia si el elemento se traslada: con
        # el id guardado se lo reconoce y se renombra, en vez de crear otro.
        ids_guardados = {
            x.id_externo: e.codigo
            for e in elementos
            for x in e.externos
            if x.sistema == self.sistema and e.codigo not in existentes
        }
        if ids_guardados:
            for host in self.cliente.llamar(
                "host.get",
                {
                    "output": ["hostid", "host", "name"],
                    "hostids": list(ids_guardados),
                    "selectHostGroups": ["name"],
                    "selectTags": ["tag", "value"],
                },
            ):
                existentes.setdefault(ids_guardados[host["hostid"]], host)

        acciones = []
        for elemento in elementos:
            propio = self._propio(elemento)
            host = existentes.get(elemento.codigo)
            if host is None:
                acciones.append(
                    Accion(
                        "crear",
                        elemento.codigo,
                        {**propio, "host": elemento.codigo, "ip": elemento.direccion_ip},
                        detalle=f"{elemento.direccion_ip} en {', '.join(propio['grupos'])}",
                    )
                )
                continue

            # Lo ajeno a NetDoc se conserva tal cual.
            grupos_ajenos = [
                g["name"] for g in host.get("hostgroups", [])
                if not g["name"].startswith(f"{self.grupo_raiz}/")
            ]
            etiquetas_ajenas = [
                {"tag": t["tag"], "value": t["value"]} for t in host.get("tags", [])
                if not t["tag"].startswith(PREFIJO_ETIQUETA)
            ]
            actuales = {
                "name": host["name"],
                "grupos": sorted(g["name"] for g in host.get("hostgroups", [])
                                 if g["name"].startswith(f"{self.grupo_raiz}/")),
                "tags": sorted(
                    ({"tag": t["tag"], "value": t["value"]} for t in host.get("tags", [])
                     if t["tag"].startswith(PREFIJO_ETIQUETA)),
                    key=lambda t: t["tag"],
                ),
            }
            renombrar = host["host"] != elemento.codigo
            if actuales == propio and not renombrar:
                acciones.append(Accion("sin_cambios", elemento.codigo, id_externo=host["hostid"]))
                continue
            distintos = [clave for clave in propio if propio[clave] != actuales[clave]]
            if renombrar:
                distintos.insert(0, f"host (era {host['host']})")
            acciones.append(
                Accion(
                    "actualizar",
                    elemento.codigo,
                    {
                        "host": elemento.codigo,
                        "name": propio["name"],
                        "grupos": grupos_ajenos + propio["grupos"],
                        "tags": etiquetas_ajenas + propio["tags"],
                    },
                    id_externo=host["hostid"],
                    detalle="cambia " + ", ".join(distintos),
                )
            )
        return acciones

    # --- Ejecución ----------------------------------------------------------
    def _ids_de_grupos(self, nombres: list[str]) -> list[dict]:
        faltan = [n for n in nombres if n not in self._grupos]
        if faltan:
            for grupo in self.cliente.llamar(
                "hostgroup.get", {"output": ["groupid", "name"], "filter": {"name": faltan}}
            ):
                self._grupos[grupo["name"]] = grupo["groupid"]
            for nombre in faltan:
                if nombre not in self._grupos:
                    creado = self.cliente.llamar("hostgroup.create", {"name": nombre})
                    self._grupos[nombre] = creado["groupids"][0]
        return [{"groupid": self._grupos[n]} for n in nombres]

    def _plantillas(self) -> list[dict]:
        if not self.plantillas:
            return []
        encontradas = self.cliente.llamar(
            "template.get", {"output": ["templateid", "host"], "filter": {"host": self.plantillas}}
        )
        faltan = set(self.plantillas) - {t["host"] for t in encontradas}
        if faltan:
            raise ErrorConector(f"No existen en Zabbix las plantillas: {', '.join(sorted(faltan))}")
        return [{"templateid": t["templateid"]} for t in encontradas]

    def aplicar(self, accion: Accion) -> str:
        if accion.tipo == "sin_cambios":
            return accion.id_externo or ""
        grupos = self._ids_de_grupos(accion.datos["grupos"])
        if accion.tipo == "actualizar":
            self.cliente.llamar(
                "host.update",
                {
                    "hostid": accion.id_externo,
                    "host": accion.datos["host"],
                    "name": accion.datos["name"],
                    "groups": grupos,
                    "tags": accion.datos["tags"],
                },
            )
            return accion.id_externo or ""

        creado = self.cliente.llamar(
            "host.create",
            {
                "host": accion.datos["host"],
                "name": accion.datos["name"],
                "groups": grupos,
                "tags": accion.datos["tags"],
                "templates": self._plantillas(),
                "interfaces": [
                    {
                        "type": 2,  # SNMP
                        "main": 1,
                        "useip": 1,
                        "ip": accion.datos["ip"],
                        "dns": "",
                        "port": "161",
                        "details": {"version": 2, "bulk": 1, "community": self.comunidad_snmp},
                    }
                ],
            },
        )
        return creado["hostids"][0]
