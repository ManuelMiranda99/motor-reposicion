"""Utilidades de las pruebas de la revisión independiente (no son fixtures del producto)."""

from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

import pandas as pd

from reposicion.parametros import Configs
from tests.sinteticos import FAMILIAS, preparar_data
from tests.unit.test_backtest import NEGOCIO
from tests.unit.test_publicacion import cfg_modelo


def configs(cfg_fuentes, cfg_validacion) -> Configs:
    """Configuración pequeña (baseline + LightGBM diminuto), igual a la de las pruebas unitarias."""
    return Configs(cfg_modelo(), NEGOCIO, cfg_fuentes, cfg_validacion)


def copiar_bandeja(origen: Path, destino: Path) -> Path:
    """Copia de la bandeja sintética para poder agregarle archivos (la original es de sesión)."""
    shutil.copytree(origen, destino)
    return destino


def nuevo_dir_data(historico: Path, destino: Path) -> Path:
    return preparar_data(destino, historico)


def escribir_ventas(bandeja: Path, entrega: date, fecha_dato: date, tiendas: list[int]) -> Path:
    """Escribe un `ventas_<fecha_dato>.csv` bien formado en la carpeta `<entrega>`."""
    filas = [
        {"date": fecha_dato.isoformat(), "store_nbr": s, "family": f, "sales": 10.0 + s}
        for s in tiendas
        for f in FAMILIAS
    ]
    ruta = bandeja / entrega.isoformat() / f"ventas_{fecha_dato.isoformat()}.csv"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(filas).to_csv(ruta, index=False)
    return ruta


def fila_ledger(ledger: pd.DataFrame, archivo: str) -> pd.Series:
    f = ledger[ledger["archivo"] == archivo]
    assert len(f) == 1, f"{archivo} no está en el ledger"
    return f.iloc[0]
