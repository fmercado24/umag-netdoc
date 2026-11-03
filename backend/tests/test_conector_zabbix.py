"""Conector con Zabbix contra una API simulada."""

from __future__ import annotations

from sqlalchemy import select

from app.integraciones import ConectorZabbix
from app.models import Elemento
from app.scripts.sincronizar import sincronizar

API = "/api/v1"
PLANTILLA = "Network Generic Device by SNMP"


class ZabbixFalso:
    """Lo justo de ``api_jsonrpc.php`` para el conector."""

    def __init__(self) -> None:
        self.grupos = {"Equipos de red": "1"}  # nombre → id
        self.plantillas = {PLANTILLA: "10226"}
        self.hosts: list[dict] = []
        self.llamadas: list[tuple[str, dict]] = []
        self._siguiente = 100

    def _id(self) -> str:
        self._siguiente += 1
        return str(self._siguiente)

    def _guardar(self, host: dict, p: dict) -> None:
        nombres = {i: n for n, i in self.grupos.items()}
        host.update(
            name=p["name"],
            hostgroups=[{"name": nombres[g["groupid"]]} for g in p["groups"]],
            tags=p["tags"],
        )

    def llamar(self, metodo: str, p: dict):
        self.llamadas.append((metodo, p))
        if metodo == "host.get":
            if "hostids" in p:
                return [h for h in self.hosts if h["hostid"] in p["hostids"]]
            return [h for h in self.hosts if h["host"] in p["filter"]["host"]]
        if metodo == "hostgroup.get":
            return [{"groupid": i, "name": n} for n, i in self.grupos.items() if n in p["filter"]["name"]]
        if metodo == "hostgroup.create":
            self.grupos[p["name"]] = self._id()
            return {"groupids": [self.grupos[p["name"]]]}
        if metodo == "template.get":
            return [{"templateid": i, "host": n} for n, i in self.plantillas.items() if n in p["filter"]["host"]]
        if metodo == "host.create":
            host = {"hostid": self._id(), "host": p["host"]}
            self._guardar(host, p)
            self.hosts.append(host)
            return {"hostids": [host["hostid"]]}
        if metodo == "host.update":
            host = next(h for h in self.hosts if h["hostid"] == p["hostid"])
            host["host"] = p["host"]
            self._guardar(host, p)
            return {"hostids": [p["hostid"]]}
        raise AssertionError(f"método inesperado: {metodo}")

    def metodos(self) -> list[str]:
        return [m for m, _ in self.llamadas]


def _preparar(cliente) -> tuple[str, str]:
    cliente.post(f"{API}/edificios", json={"codigo": "ZBX", "nombre": "Edificio de prueba"})
    cliente.post(f"{API}/edificios/ZBX/pisos", json={"codigo": "P01", "orden": 1})

    def crear(**extra):
        return cliente.post(
            f"{API}/elementos", json={"tipo": "SW", "edificio": "ZBX", "piso": "P01", **extra}
        ).json()["codigo"]

    nuevo = crear(direccion_ip="10.90.0.1", etiqueta="SW-CORE")
    existente = crear(direccion_ip="10.90.0.2")
    crear()  # sin IP: no se lleva a Zabbix
    return nuevo, existente


def test_plan_crea_actualiza_y_respeta_lo_ajeno(cliente, sesion):
    nuevo, existente = _preparar(cliente)
    zabbix = ZabbixFalso()
    # Ya estaba en Zabbix, con un grupo y una etiqueta puestos a mano.
    zabbix.hosts.append(
        {
            "hostid": "55",
            "host": existente,
            "name": existente,
            "hostgroups": [{"name": "Equipos de red"}],
            "tags": [{"tag": "sitio", "value": "umag"}, {"tag": "netdoc_piso", "value": "P99"}],
        }
    )
    conector = ConectorZabbix(zabbix, tipos={"SW"}, plantillas=[PLANTILLA])

    # Sin --aplicar solo se consulta.
    plan = sincronizar(sesion, conector, edificio="ZBX")
    assert plan["plan"] == {"crear": 1, "actualizar": 1}
    assert zabbix.metodos() == ["host.get"]

    resultado = sincronizar(sesion, conector, aplicar=True, edificio="ZBX")
    assert resultado["errores"] == []

    creado = next(p for m, p in zabbix.llamadas if m == "host.create")
    assert creado["host"] == nuevo
    assert creado["name"] == f"{nuevo} SW-CORE"
    assert creado["interfaces"][0]["ip"] == "10.90.0.1"
    assert creado["interfaces"][0]["type"] == 2
    assert creado["templates"] == [{"templateid": "10226"}]
    assert {"NetDoc/ZBX", "NetDoc/ZBX/P01"} <= set(zabbix.grupos)

    actualizado = next(h for h in zabbix.hosts if h["hostid"] == "55")
    assert {g["name"] for g in actualizado["hostgroups"]} == {"Equipos de red", "NetDoc/ZBX", "NetDoc/ZBX/P01"}
    assert {"tag": "sitio", "value": "umag"} in actualizado["tags"]
    assert {"tag": "netdoc_piso", "value": "P01"} in actualizado["tags"]

    ids = {
        e.codigo: [(x.sistema, x.id_externo) for x in e.externos]
        for e in sesion.scalars(select(Elemento).where(Elemento.codigo.in_([nuevo, existente]))).unique()
    }
    assert ids[existente] == [("zabbix", "55")]
    assert ids[nuevo][0][0] == "zabbix"

    # Una segunda pasada no tiene nada que hacer.
    segunda = sincronizar(sesion, ConectorZabbix(zabbix, tipos={"SW"}), edificio="ZBX")
    assert segunda["plan"] == {"sin_cambios": 2}


def test_un_elemento_trasladado_renombra_su_host_en_vez_de_duplicarlo(cliente, sesion):
    cliente.post(f"{API}/edificios", json={"codigo": "ZBT", "nombre": "Edificio de prueba"})
    for piso in ("P01", "P02"):
        cliente.post(f"{API}/edificios/ZBT/pisos", json={"codigo": piso, "orden": 1})
    codigo = cliente.post(
        f"{API}/elementos",
        json={"tipo": "SW", "edificio": "ZBT", "piso": "P01", "direccion_ip": "10.91.0.1"},
    ).json()["codigo"]
    zabbix = ZabbixFalso()
    zabbix._siguiente = 5000  # Los ids de otras pruebas siguen en la base.
    conector = ConectorZabbix(zabbix, tipos={"SW"}, plantillas=[PLANTILLA])
    assert sincronizar(sesion, conector, aplicar=True, edificio="ZBT")["errores"] == []
    sesion.commit()
    assert [h["host"] for h in zabbix.hosts] == [codigo]

    respuesta = cliente.post(f"{API}/elementos/{codigo}/trasladar", json={"piso": "P02"})
    assert respuesta.status_code == 200, respuesta.text
    nuevo = respuesta.json()["codigo"]
    assert nuevo == "ZBT-SW01-P02"

    sesion.expire_all()
    assert sincronizar(sesion, conector, edificio="ZBT")["plan"] == {"actualizar": 1}
    assert sincronizar(sesion, conector, aplicar=True, edificio="ZBT")["errores"] == []
    sesion.commit()
    assert [h["host"] for h in zabbix.hosts] == [nuevo]
    assert zabbix.metodos().count("host.create") == 1

    sesion.expire_all()
    assert sincronizar(sesion, conector, edificio="ZBT")["plan"] == {"sin_cambios": 1}
