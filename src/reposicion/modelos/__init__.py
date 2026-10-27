"""Modelos de pronóstico disponibles, por nombre."""

from __future__ import annotations

from collections.abc import Callable

from reposicion.modelos.base import ModeloPronostico
from reposicion.modelos.baseline import Baseline
from reposicion.parametros import Configs


def fabrica(nombre: str, cfgs: Configs) -> Callable[[], ModeloPronostico]:
    """Devuelve una función sin argumentos que crea un modelo nuevo sin entrenar."""
    if nombre == "baseline":
        return lambda: Baseline(cfgs.modelo)
    raise ValueError(f"modelo desconocido: {nombre!r}")
