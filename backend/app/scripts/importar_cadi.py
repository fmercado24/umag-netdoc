"""Atajo histórico: equivale a ``python -m app.scripts.importar_edificio CADI``.

    python -m app.scripts.importar_cadi [--recargar] [--solo-advertencias]

El importador es genérico; ver ``app.scripts.importar_edificio`` y
``docs/guia-nuevo-edificio.md`` para cargar otros edificios.
"""

from __future__ import annotations

import sys

from app.scripts.importar_edificio import main as _importar


def main() -> None:
    _importar(["CADI", *sys.argv[1:]])


if __name__ == "__main__":
    main()
