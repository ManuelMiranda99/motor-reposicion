"""Interfaz común de los modelos de pronóstico y utilidades de cuantiles."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

import numpy as np
import pandas as pd

from reposicion.parametros import ConfigModelo, ConfigNegocio


class ModeloPronostico(Protocol):
    nombre: str

    def ajustar(self, X: pd.DataFrame, y: pd.Series) -> ModeloPronostico: ...

    def predecir_cuantiles(self, X: pd.DataFrame, cuantiles: list[float]) -> pd.DataFrame:
        """Columnas `q0.10`, `q0.50`, …; valores >= 0 y monótonos por fila; mismo índice que X."""
        ...

    def guardar(self, ruta: Path) -> None: ...

    @classmethod
    def cargar(cls, ruta: Path) -> ModeloPronostico: ...


def nombre_cuantil(q: float) -> str:
    """0.1 -> "q0.10", 0.4 -> "q0.40"."""
    return f"q{q:.2f}"


def cuantil_de_nombre(nombre: str) -> float:
    return float(nombre.removeprefix("q"))


def cuantiles_requeridos(cfg_modelo: ConfigModelo, cfg_negocio: ConfigNegocio) -> list[float]:
    """Cuantiles de reporte ∪ τ de cada grupo de costos, ordenados y sin repetir."""
    from reposicion.pedido import cuantil_critico

    taus = [cuantil_critico(g.c_quiebre, g.c_merma) for g in cfg_negocio.grupos.values()]
    return sorted({round(q, 2) for q in [*cfg_modelo.cuantiles_reporte, *taus]})


def ordenar_cuantiles(df: pd.DataFrame) -> pd.DataFrame:
    """Ordena cada fila de menor a mayor para que los cuantiles no se crucen."""
    return pd.DataFrame(np.sort(df.to_numpy(), axis=1), index=df.index, columns=df.columns)


def aplicar_regla_ceros(valores: np.ndarray, X: pd.DataFrame, dias_sin_ventas: int) -> np.ndarray:
    """Serie sin ventas en más de `dias_sin_ventas` días → pronóstico 0 (única definición)."""
    sin_ventas = X["dias_desde_venta"].to_numpy() > dias_sin_ventas
    return np.where(sin_ventas, 0.0, valores)
