"""La contraseña se define fuera del repositorio, en .env."""

from __future__ import annotations

import shutil
import stat
import subprocess
from pathlib import Path

import pytest
from dotenv import dotenv_values
from sqlalchemy import func, select

from app.core.config import configuracion
from app.db.session import SesionLocal
from app.models import IntentoIngreso
from app.scripts import definir_clave
from app.scripts.definir_clave import ClaveRechazada, guardar_hash, validar_clave
from app.servicios.autenticacion import cifrar_clave

RAIZ = Path(__file__).resolve().parents[2]


def _git(*argumentos: str) -> subprocess.CompletedProcess:
    """Omite la prueba si no hay git o esto no es un repositorio."""
    if shutil.which("git") is None:
        pytest.skip("Sin git")
    resultado = subprocess.run(
        ["git", *argumentos], cwd=RAIZ, capture_output=True, text=True, check=False
    )
    if resultado.returncode > 1:
        pytest.skip("Sin repositorio git")
    return resultado


def test_el_archivo_de_la_contrasena_no_se_versiona():
    # Si falla: .env dejó de estar en .gitignore y el hash podría subirse.
    assert _git("check-ignore", "-q", ".env").returncode == 0


def test_el_repositorio_no_trae_ningun_hash_de_contrasena():
    # Si falla: hay un hash Argon2id en un archivo versionable. Debe vivir en .env.
    patron = r"\$argon2id\$v=[0-9]+\$m=[0-9]+,t=[0-9]+,p=[0-9]+\$[A-Za-z0-9+/]{16}"
    assert _git("grep", "--untracked", "-lE", patron).stdout == ""


@pytest.mark.parametrize("clave", ["corta", "", "1234567"])
def test_rechaza_las_cortas(clave):
    with pytest.raises(ClaveRechazada, match="al menos 8"):
        validar_clave(clave, "admin-netdoc")


@pytest.mark.parametrize("clave", ["admin-netdoc", "xADMIN-NETDOCx"])
def test_rechaza_las_que_contienen_el_usuario(clave):
    with pytest.raises(ClaveRechazada, match="nombre de usuario"):
        validar_clave(clave, "admin-netdoc")


def test_acepta_una_de_ocho_caracteres():
    validar_clave("abcd1234", "admin-netdoc")


def test_guardar_hash_conserva_las_demas_variables(tmp_path):
    archivo = tmp_path / ".env"
    archivo.write_text("NETDOC_MONITOREO_TOKEN=abc\n# comentario\n", encoding="utf-8")
    guardar_hash("primero", archivo)
    guardar_hash("segundo", archivo)

    assert archivo.read_text(encoding="utf-8").splitlines() == [
        "NETDOC_MONITOREO_TOKEN=abc",
        "# comentario",
        "NETDOC_ADMIN_CLAVE_HASH='segundo'",
    ]


def test_el_archivo_queda_legible_solo_para_su_dueno(tmp_path):
    archivo = tmp_path / ".env"
    archivo.write_text("", encoding="utf-8")
    archivo.chmod(0o644)
    guardar_hash("x", archivo)
    assert stat.S_IMODE(archivo.stat().st_mode) == 0o600
    assert list(tmp_path.iterdir()) == [archivo]  # sin temporales


def test_el_hash_se_lee_tal_cual_a_pesar_de_sus_signos_de_dolar(tmp_path):
    archivo = tmp_path / ".env"
    valor = cifrar_clave("una-clave-de-prueba")
    guardar_hash(valor, archivo)
    assert dotenv_values(archivo)["NETDOC_ADMIN_CLAVE_HASH"] == valor


def test_si_falta_no_hace_nada_si_ya_hay_una(monkeypatch, tmp_path):
    monkeypatch.setattr(configuracion, "admin_clave_hash", cifrar_clave("una-clave-de-prueba"))
    monkeypatch.setattr(definir_clave, "ARCHIVO_ENV", tmp_path / ".env")
    monkeypatch.setattr("sys.argv", ["definir_clave", "--si-falta"])
    assert definir_clave.main() == 0
    assert not (tmp_path / ".env").exists()


def test_sin_terminal_no_se_queda_esperando(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(configuracion, "admin_clave_hash", "")
    monkeypatch.setattr(definir_clave, "ARCHIVO_ENV", tmp_path / ".env")
    monkeypatch.setattr("sys.argv", ["definir_clave", "--si-falta"])
    monkeypatch.setattr("sys.stdin.isatty", lambda: False, raising=False)
    assert definir_clave.main() == 1
    assert "definir_clave" in capsys.readouterr().err
    assert not (tmp_path / ".env").exists()


def test_desbloquear_borra_los_intentos_sin_tocar_la_contrasena(monkeypatch, tmp_path):
    with SesionLocal() as bd:
        bd.add(IntentoIngreso(cliente="10.0.0.1", ocurrido_en=1.0))
        bd.commit()
    monkeypatch.setattr(definir_clave, "ARCHIVO_ENV", tmp_path / ".env")
    monkeypatch.setattr("sys.argv", ["definir_clave", "--desbloquear"])

    assert definir_clave.main() == 0

    with SesionLocal() as bd:
        assert bd.scalar(select(func.count()).select_from(IntentoIngreso)) == 0
    assert not (tmp_path / ".env").exists()
