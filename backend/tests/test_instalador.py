"""Lo que instalar-servidor.sh hace como root antes de instalar: dejar la carpeta
del repositorio a nombre de quien ejecuta sudo y revisar si hay una versión
nueva en GitHub (deploy/servidor/probar-instalador.sh)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

GUION = Path(__file__).resolve().parents[2] / "deploy" / "servidor" / "probar-instalador.sh"


@pytest.mark.skipif(shutil.which("git") is None, reason="sin git")
def test_el_instalador_revisa_la_version_y_la_carpeta():
    resultado = subprocess.run(
        ["bash", str(GUION)], capture_output=True, text=True, timeout=300, check=False
    )
    assert resultado.returncode == 0, resultado.stdout + resultado.stderr
    assert "Todas las pruebas del instalador pasaron" in resultado.stdout
