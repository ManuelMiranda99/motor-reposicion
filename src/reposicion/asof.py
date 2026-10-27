"""Lectura "as-of": exactamente lo que se sabía en la fecha de corte.

Toda lectura de datos para features, entrenamiento, pronóstico o monitoreo pasa por `asof`. La
fecha de corte siempre llega como parámetro; nunca se consulta el reloj.
"""

from __future__ import annotations

from collections.abc import Collection
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from reposicion.almacen import leer_limpio


def asof(fuente: str, corte: date, dir_data: Path) -> pd.DataFrame:
    """Datos de `fuente` visibles en `corte` (las entregas del propio día cuentan).

    1. Solo filas con `fecha_disponible <= corte`.
    2. Por cada `fecha_dato`, solo la versión máxima disponible.
    3. En snapshots (`tiendas`), solo el de mayor `fecha_dato`.
    """
    df = leer_limpio(dir_data, fuente)
    df = df[df["fecha_disponible"] <= pd.Timestamp(corte)]
    if df.empty:
        return df.drop(columns=["version", "origen"]).reset_index(drop=True)
    if fuente == "tiendas":
        df = df[df["fecha_dato"] == df["fecha_dato"].max()]
    maxima = df.groupby("fecha_dato")["version"].transform("max")
    df = df[df["version"] == maxima]
    return df.drop(columns=["version", "origen"]).reset_index(drop=True)


def ultima_fecha_disponible(fuente: str, corte: date, dir_data: Path) -> date | None:
    """Última `fecha_dato` visible en `corte`, o `None` si no hay datos."""
    df = asof(fuente, corte, dir_data)
    if df.empty:
        return None
    return df["fecha_dato"].max().date()


def fechas_faltantes(
    fuente: str,
    corte: date,
    ventana_dias: int,
    dir_data: Path,
    dias_sin_operacion: Collection[str] = (),
) -> list[date]:
    """Huecos en `[corte - ventana, corte - 1]`: días sin datos visibles en `corte`.

    `dias_sin_operacion` son mes-día (`"12-25"`) sin datos por diseño. No aplicar a fuentes con
    huecos normales (petróleo).
    """
    visibles = set(asof(fuente, corte, dir_data)["fecha_dato"].dt.date)
    huecos = []
    for k in range(ventana_dias, 0, -1):
        d = corte - timedelta(days=k)
        if d not in visibles and d.strftime("%m-%d") not in dias_sin_operacion:
            huecos.append(d)
    return huecos
