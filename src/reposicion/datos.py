"""Carga de todas las fuentes visibles en una fecha de corte (siempre vía `asof`)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from reposicion.asof import asof

FUENTES_MODELO = ["ventas", "promociones", "transacciones", "petroleo", "feriados", "tiendas"]


def cargar_datos_asof(corte: date, dir_data: Path) -> dict[str, pd.DataFrame]:
    """Lee cada fuente una sola vez, tal como se conocía en `corte`."""
    return {fuente: asof(fuente, corte, dir_data) for fuente in FUENTES_MODELO}
