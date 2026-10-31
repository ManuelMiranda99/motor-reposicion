"""Modelos de pronóstico disponibles, por nombre."""

from __future__ import annotations

from collections.abc import Callable

from reposicion.modelos.base import ModeloPronostico, cuantiles_requeridos
from reposicion.modelos.baseline import Baseline
from reposicion.modelos.lgbm import LightGBMCuantiles
from reposicion.parametros import Configs


def fabrica(nombre: str, cfgs: Configs) -> Callable[[], ModeloPronostico]:
    """Devuelve una función sin argumentos que crea un modelo nuevo sin entrenar."""
    if nombre == "baseline":
        return lambda: Baseline(cfgs.modelo)
    if nombre == "lgbm":
        cuantiles = cuantiles_requeridos(cfgs.modelo, cfgs.negocio)
        return lambda: LightGBMCuantiles(cfgs.modelo, cuantiles)
    raise ValueError(f"modelo desconocido: {nombre!r}")


def clase_de(tipo: str) -> type[ModeloPronostico]:
    """Clase del modelo según su tipo (para `cargar`)."""
    if tipo == "baseline":
        return Baseline
    if tipo == "lgbm":
        return LightGBMCuantiles
    raise ValueError(f"modelo desconocido: {tipo!r}")
