"""Carga de archivos de configuración versionados (`config/*.yaml`)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def cargar_yaml(ruta: str | Path) -> dict[str, Any]:
    """Lee un YAML y garantiza que la raíz sea un diccionario."""
    with open(ruta, encoding="utf-8") as f:
        contenido = yaml.safe_load(f) or {}
    if not isinstance(contenido, dict):
        raise ValueError(f"{ruta}: la raíz del YAML debe ser un diccionario")
    return contenido
