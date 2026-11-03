"""Carga en bloque de fotografías del levantamiento."""

from __future__ import annotations

from app.scripts.cargar_fotografias import cargar

API = "/api/v1"
JPG = b"\xff\xd8\xff"


def test_una_foto_corrupta_se_omite_sin_detener_la_carga(cliente, sesion, tmp_path):
    cliente.post(f"{API}/edificios/CADI/pisos", json={"codigo": "P38", "orden": 38})
    codigo = cliente.post(
        f"{API}/elementos", json={"tipo": "SW", "edificio": "CADI", "piso": "P38"}
    ).json()["codigo"]
    (tmp_path / f"{codigo}.jpg").write_bytes(b"no es una foto")
    (tmp_path / f"{codigo}_2.jpg").write_bytes(JPG)

    cargadas, omitidas = cargar(sesion, tmp_path, "CADI")
    sesion.commit()
    assert cargadas == 1
    assert omitidas == [f"{codigo}.jpg: El contenido del archivo no corresponde a un .jpg"]


def test_carga_por_codigo_sin_duplicar(cliente, sesion, tmp_path):
    cliente.post(f"{API}/edificios/CADI/pisos", json={"codigo": "P29", "orden": 29})
    codigo = cliente.post(
        f"{API}/elementos", json={"tipo": "SW", "edificio": "CADI", "piso": "P29"}
    ).json()["codigo"]
    (tmp_path / f"{codigo}.jpg").write_bytes(JPG + b"frente")
    (tmp_path / f"{codigo.lower()}_2.JPG").write_bytes(JPG + b"posterior")
    (tmp_path / "CADI-SW99-P29.jpg").write_bytes(JPG)
    (tmp_path / "notas.txt").write_text("no es foto")

    cargadas, omitidas = cargar(sesion, tmp_path, "CADI")
    sesion.commit()
    assert cargadas == 2
    assert omitidas == ["CADI-SW99-P29.jpg: no hay un elemento CADI-SW99-P29 en CADI"]

    fotos = cliente.get(f"{API}/elementos/{codigo}").json()["fotografias"]
    assert [f["archivo"] for f in fotos] == [
        f"fotografias/{codigo}_1.jpg",
        f"fotografias/{codigo}_2.jpg",
    ]
    assert cliente.get(f"/media/{fotos[1]['archivo']}").content == JPG + b"posterior"

    # Una segunda pasada no duplica nada.
    assert cargar(sesion, tmp_path, "CADI")[0] == 0
