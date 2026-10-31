"""Ubicación de los datos y de la bandeja.

Solo la CLI y los DAGs llaman a estas funciones; la lógica siempre recibe las rutas por parámetro.
"""

from __future__ import annotations

import os
from pathlib import Path

RAIZ_REPO = Path(__file__).resolve().parents[2]


def dir_repo() -> Path:
    """Raíz del repo (`REPOSICION_REPO` en Docker, por defecto la del paquete)."""
    return Path(os.environ.get("REPOSICION_REPO") or RAIZ_REPO)


def dir_data() -> Path:
    """Raíz de los datos versionados con DVC (`REPOSICION_DATA`, por defecto `<repo>/data`)."""
    return Path(os.environ.get("REPOSICION_DATA") or RAIZ_REPO / "data")


def dir_bandeja() -> Path:
    """Bandeja del sistema de origen (`REPOSICION_BANDEJA`, por defecto `<repo>/bandeja_sim`)."""
    return Path(os.environ.get("REPOSICION_BANDEJA") or RAIZ_REPO / "bandeja_sim")
