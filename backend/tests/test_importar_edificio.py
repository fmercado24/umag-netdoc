"""Importador genérico de edificios (y su atajo para el CADI)."""

from __future__ import annotations

import sys

import pytest

from app.db.session import SesionLocal
from app.scripts import importar_cadi
from app.scripts.importar_edificio import DIR_DATA, ReglasLamina, contar_elementos, main

API = "/api/v1"
ENCABEZADO = "Elemento,Etiqueta,Tipo,Ubicación,Estado Operativo,Estado Condición,Notas,Rack,Foto\n"
ENCABEZADO_PD = (
    "Elemento,Etiqueta,Tipo,Ubicación (Hacia dónde va el cable),Estado Operativo,"
    "Estado Condición,Notas\n"
)


@pytest.fixture
def planillas_cadi(tmp_path):
    (tmp_path / "cadi-p01-t1.csv").write_text(
        ENCABEZADO + "EdgeSwitch24 LITE,SW-TEL,switches,Sala Eléctrica,Operativo,Regular,,Rack-01,\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def base_poblada(cliente) -> int:
    cliente.post(f"{API}/edificios/CADI/pisos", json={"codigo": "P01", "orden": 1})
    cliente.post(f"{API}/elementos", json={"tipo": "UPS", "edificio": "CADI", "piso": "P01"})
    with SesionLocal() as sesion:
        return contar_elementos(sesion, "CADI")


def test_solo_advertencias_no_modifica_una_base_poblada(base_poblada, planillas_cadi, capsys):
    main(["CADI", "--datos", str(planillas_cadi), "--solo-advertencias"])

    with SesionLocal() as sesion:
        assert contar_elementos(sesion, "CADI") == base_poblada
    # El informe sale completo: el switch declara un rack sin ficha.
    assert "CADI-R01-P01-T1" in capsys.readouterr().out


def test_reimportar_sin_recargar_se_detiene_con_un_mensaje(base_poblada, planillas_cadi):
    with pytest.raises(SystemExit, match="--recargar"):
        main(["CADI", "--datos", str(planillas_cadi)])

    with SesionLocal() as sesion:
        assert contar_elementos(sesion, "CADI") == base_poblada


def test_el_atajo_importar_cadi_sigue_funcionando(planillas_cadi, monkeypatch, capsys):
    monkeypatch.setattr(
        sys, "argv", ["importar_cadi", "--datos", str(planillas_cadi), "--solo-advertencias"]
    )
    importar_cadi.main()
    assert "CADI-R01-P01-T1" in capsys.readouterr().out


def test_edificio_que_no_esta_en_el_catalogo(tmp_path):
    with pytest.raises(SystemExit, match="No existe el edificio XYZ"):
        main(["XYZ", "--datos", str(tmp_path)])


def test_reglas_de_lamina_del_cadi():
    reglas = ReglasLamina.desde_csv(DIR_DATA / "cadi" / "cadi-laminas.csv")
    # La sala eléctrica cuenta como tramo 3 pero se dibuja en la lámina del 1.
    assert reglas.lamina("P01", "T3", "Sala Eléctrica 1068 Rack-01") == "T1"
    assert reglas.lamina("P01", "T3", "Box 3 1031 P01-T3-R02-D05") == "T1"
    # El auditorio y su sala de control sí están en la lámina del tramo 3.
    assert reglas.lamina("P01", "T3", "Escenario Auditorio 1076") is None
    assert reglas.lamina("P01", "T3", "Sala Eléctrica 1068 Auditorio P1-T3-APX") is None
    assert reglas.lamina("P01", "T3", "Sala de Control 1072") is None
    assert reglas.lamina("P01", "T3", "Hall 1061") == "T2"
    assert reglas.lamina("P01", "T2", "Oficina 1083") is None


def test_importa_otro_edificio_con_sus_propios_archivos(cliente, tmp_path):
    # Facultad de Ciencias (CS): un piso con tramos y otro sin ellos.
    (tmp_path / "cs-p01-t1.csv").write_text(
        ENCABEZADO
        + "Rack 42U,RACK-02,Racks,Sala de Comunicaciones 101,Operativo,Excelente,,Rack-02,\n"
        + "Cisco CBS350,SW-CORE,Switches,Sala de Comunicaciones 101,Operativo,Excelente,,Rack-02,\n",
        encoding="utf-8",
    )
    (tmp_path / "cs-p02.csv").write_text(
        ENCABEZADO + "UniFi U6 Pro,AP-LAB,Access Points,Laboratorio 201,Operativo,Excelente,,,\n",
        encoding="utf-8",
    )
    (tmp_path / "cs-puntos-de-datos.csv").write_text(
        ENCABEZADO_PD
        + "Roseta Laboratorio 105,P01-T1-R2-D01,Punto de datos,Piso 1 - Tramo 1,Operativo,Excelente,\n",
        encoding="utf-8",
    )
    # La misma VLAN 3 que el CADI, con otra red: cada edificio tiene la suya.
    (tmp_path / "cs-vlans.csv").write_text(
        "numero,nombre,gateway,prefijo,servicio\n3,DATOS CS,10.50.0.1,/16,datos\n",
        encoding="utf-8",
    )
    (tmp_path / "cs-laminas.csv").write_text(
        "piso,tramo,recinto,lamina,motivo\nP01,T1,laboratorio 105,T2,Dibujado en la lámina 2\n",
        encoding="utf-8",
    )

    main(["CS", "--datos", str(tmp_path)])

    codigos = {
        e["codigo"]: e
        for e in cliente.get(f"{API}/integraciones/inventario?edificio=CS&limite=5000").json()["elementos"]
    }
    assert set(codigos) == {"CS-R02-P01-T1", "CS-SW01-P01-T1", "CS-AP01-P02", "CS-PD-P01-T1-R02-D01"}
    assert codigos["CS-SW01-P01-T1"]["ubicacion"]["contenedor"] == "CS-R02-P01-T1"
    punto = codigos["CS-PD-P01-T1-R02-D01"]
    assert punto["atributos"]["vlan_por_defecto"] == 3
    assert (punto["ubicacion"]["recinto"], punto["ubicacion"]["lamina"]) == ("Laboratorio 105", "T2")

    vlans = cliente.get(f"{API}/vlans?edificio=CS").json()
    assert [(v["numero"], v["subred"]) for v in vlans] == [(3, "10.50.0.1/16")]


def test_pendientes_importa_solo_los_edificios_nuevos(tmp_path, monkeypatch, capsys):
    from app.scripts import importar_edificio

    for carpeta in ("ped", "_plantilla", "xyz"):
        (tmp_path / carpeta).mkdir()
        (tmp_path / carpeta / f"{carpeta}-p01.csv").write_text(
            ENCABEZADO + "Cisco CBS250,SW-PED,Switches,Sala 12,Operativo,Excelente,,,\n",
            encoding="utf-8",
        )
    monkeypatch.setattr(importar_edificio, "DIR_DATA", tmp_path)

    assert importar_edificio.edificios_con_planillas() == ["PED", "XYZ"]
    importar_edificio.importar_pendientes()
    salida = capsys.readouterr().out
    assert "PED: importando" in salida
    assert "XYZ: no se importó. No existe el edificio XYZ" in salida

    importar_edificio.importar_pendientes()
    assert "PED: ya tiene 1 elementos; no se reimporta." in capsys.readouterr().out


def test_edificio_sin_tramos_carga_sus_puntos_de_datos(cliente, tmp_path):
    # Gimnasio (GIM): pisos sin tramos; rótulos P<piso>-R<rack>-<puerto>.
    (tmp_path / "gim-p01.csv").write_text(
        ENCABEZADO + "Rack mural 12U,RACK-01,Racks,Bodega 3,Operativo,Excelente,,Rack-01,\n",
        encoding="utf-8",
    )
    (tmp_path / "gim-puntos-de-datos.csv").write_text(
        ENCABEZADO_PD + "Roseta Oficina Deportes,P01-R1-D01,Punto de datos,Piso 1,Operativo,Excelente,\n",
        encoding="utf-8",
    )
    main(["GIM", "--datos", str(tmp_path)])

    registros = cliente.get(f"{API}/integraciones/inventario?edificio=GIM").json()["elementos"]
    assert {r["codigo"] for r in registros} == {"GIM-R01-P01", "GIM-PD-P01-R01-D01"}
    punto = next(r for r in registros if r["codigo"] == "GIM-PD-P01-R01-D01")
    assert (punto["ubicacion"]["tramo"], punto["ubicacion"]["recinto"]) == (None, "Oficina Deportes")


def test_acepta_planillas_de_excel_con_punto_y_coma_y_windows_1252(cliente, tmp_path, capsys):
    # Así guarda Excel con la configuración regional de Chile.
    fila = "Cisco CBS350;SW-BIBLIOTECA;Switches;Sala Técnica Ñandú;Operativo;Excelente;;;"
    (tmp_path / "bib-p01.csv").write_bytes(
        (ENCABEZADO.replace(",", ";") + fila + "\n").encode("cp1252")
    )
    main(["BIB", "--datos", str(tmp_path)])

    assert "no está en UTF-8" in capsys.readouterr().out
    registro = cliente.get(f"{API}/integraciones/inventario?edificio=BIB").json()["elementos"][0]
    assert (registro["codigo"], registro["ubicacion"]["recinto"]) == ("BIB-SW01-P01", "Sala Técnica Ñandú")


def test_agregar_suma_un_tramo_sin_tocar_lo_ya_importado(cliente, tmp_path, capsys):
    # Primer levantamiento de PLA: tramo 1 y puntos de datos del tramo 2, cuyo
    # rack aún no tiene planilla (queda inferido desde los rótulos).
    (tmp_path / "pla-p01-t1.csv").write_text(
        ENCABEZADO
        + "Rack 24U,RACK-01,Racks,Sala 101,Operativo,Excelente,,Rack-01,\n"
        + "Cisco CBS250,SW-A,Switches,Sala 101,Operativo,Excelente,,Rack-01,\n",
        encoding="utf-8",
    )
    puntos = tmp_path / "pla-puntos-de-datos.csv"
    puntos.write_text(
        ENCABEZADO_PD + "Roseta Oficina 20,P01-T2-R2-D01,Punto de datos,Piso 1 - Tramo 2,Operativo,Excelente,\n",
        encoding="utf-8",
    )
    main(["PLA", "--datos", str(tmp_path)])
    rack = cliente.get(f"{API}/elementos/PLA-R02-P01-T2").json()
    assert "Requiere verificación" in rack["observaciones"]
    # Un dato corregido a mano en el visor no debe perderse.
    cliente.patch(f"{API}/elementos/PLA-PD-P01-T2-R02-D01", json={"etiqueta": "CORREGIDA"})

    # Llega la planilla del tramo 2 y un punto de datos más.
    (tmp_path / "pla-p01-t2.csv").write_text(
        ENCABEZADO
        + "Rack mural 12U,RACK-02,Racks,Oficina 20,Operativo,Regular,,Rack-02,\n"
        + "Cisco CBS250,SW-B,Switches,Oficina 20,Operativo,Excelente,,Rack-02,\n",
        encoding="utf-8",
    )
    with puntos.open("a", encoding="utf-8") as archivo:
        archivo.write("Roseta Oficina 20,P01-T2-R2-D02,Punto de datos,Piso 1 - Tramo 2,Operativo,Excelente,\n")
    main(["PLA", "--datos", str(tmp_path), "--agregar"])
    salida = capsys.readouterr().out
    assert "pla-p01-t1.csv (ya importada)" in salida
    assert "Racks completados con su planilla: PLA-R02-P01-T2" in salida

    rack = cliente.get(f"{API}/elementos/PLA-R02-P01-T2").json()
    assert (rack["etiqueta"], rack["ubicacion_descriptiva"]) == ("RACK-02", "Oficina 20")
    # El correlativo sigue por piso y el switch queda montado en el rack completado.
    switch = cliente.get(f"{API}/elementos/PLA-SW02-P01-T2").json()
    assert switch["padre_codigo"] == "PLA-R02-P01-T2"
    assert cliente.get(f"{API}/elementos/PLA-PD-P01-T2-R02-D01").json()["etiqueta"] == "CORREGIDA"
    codigos = {
        r["codigo"] for r in cliente.get(f"{API}/integraciones/inventario?edificio=PLA").json()["elementos"]
    }
    assert codigos == {
        "PLA-R01-P01-T1", "PLA-SW01-P01-T1", "PLA-R02-P01-T2", "PLA-SW02-P01-T2",
        "PLA-PD-P01-T2-R02-D01", "PLA-PD-P01-T2-R02-D02",
    }

    # Una segunda pasada no tiene nada nuevo que sumar.
    main(["PLA", "--datos", str(tmp_path), "--agregar"])
    salida = capsys.readouterr().out
    assert "Puntos de datos que ya existían: 2" in salida
    assert "Equipos:              0" in salida


def test_columnas_opcionales_de_ip_mac_y_serie(cliente, tmp_path, capsys):
    encabezado = ENCABEZADO.rstrip("\n") + ",IP,MAC,N° de serie\n"
    (tmp_path / "rec-p01.csv").write_text(
        encabezado
        + "Cisco CBS350,SW-REC,Switches,Sala 1,Operativo,Excelente,,,,10.60.0.2,aa-bb-cc-00-11-22,FOC1234X\n"
        + "Cisco CBS250,SW-MAL,Switches,Sala 1,Operativo,Excelente,,,,10.60.0.300,,\n",
        encoding="utf-8",
    )
    main(["REC", "--datos", str(tmp_path)])

    assert "IP inválida '10.60.0.300' en SW-MAL" in capsys.readouterr().out
    registros = {
        r["codigo"]: r
        for r in cliente.get(f"{API}/integraciones/inventario?edificio=REC").json()["elementos"]
    }
    bueno = registros["REC-SW01-P01"]
    assert (bueno["red"]["direccion_ip"], bueno["red"]["direccion_mac"]) == ("10.60.0.2", "AA:BB:CC:00:11:22")
    assert bueno["equipo"]["numero_serie"] == "FOC1234X"
    assert registros["REC-SW02-P01"]["red"]["direccion_ip"] is None
