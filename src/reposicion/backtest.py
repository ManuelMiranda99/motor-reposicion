"""Backtest rolling-origin idéntico para todos los modelos.

Para cada origen de prueba O se entrena con los orígenes anteriores cuyos 14 días ya terminaron
antes de O (ventana de `ventana_origenes_semanas`) y se predice O. Los mismos orígenes y la misma
ventana se usan para todos los modelos.

Nota: el backtest usa los datos **revisados** a `corte_final` (incluye correcciones posteriores);
la operación usa as-of estricto en cada corte.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from reposicion.datos import cargar_datos_asof
from reposicion.features import construir_features
from reposicion.io import escribir_parquet
from reposicion.metricas import resumen_metricas
from reposicion.modelos.base import ModeloPronostico, cuantiles_requeridos
from reposicion.parametros import ConfigModelo, Configs

log = logging.getLogger(__name__)


def _paso_entrenamiento(cfg_modelo: ConfigModelo) -> int:
    """Días entre orígenes de entrenamiento: una semana (corte semanal)."""
    return 7


def ultimo_origen_entrenable(origen: date, cfg_modelo: ConfigModelo) -> date:
    """Último origen O' cuyos días objetivo terminan antes de `origen` (O' + h - 1 <= O - 1)."""
    paso = _paso_entrenamiento(cfg_modelo)
    return origen - timedelta(days=paso * math.ceil(cfg_modelo.horizonte_dias / paso))


def origenes_entrenamiento(origen: date, cfg_modelo: ConfigModelo) -> list[date]:
    """Orígenes semanales de entrenamiento para predecir `origen`, de más antiguo a más reciente."""
    ultimo = ultimo_origen_entrenable(origen, cfg_modelo)
    paso = _paso_entrenamiento(cfg_modelo)
    n = cfg_modelo.ventana_origenes_semanas
    return [ultimo - timedelta(days=paso * k) for k in range(n - 1, -1, -1)]


def origenes_backtest(corte_final: date, cfg_modelo: ConfigModelo) -> list[date]:
    """Los últimos `n_origenes` días de corte O con O + horizonte - 1 <= corte_final - 1.

    Así los 14 días de cada origen ya se conocen en `corte_final`.
    """
    limite = corte_final - timedelta(days=cfg_modelo.horizonte_dias)
    ultimo = limite - timedelta(days=(limite.weekday() - cfg_modelo.dia_corte) % 7)
    bt = cfg_modelo.backtest
    return [ultimo - timedelta(days=bt.paso_dias * k) for k in range(bt.n_origenes - 1, -1, -1)]


def ejecutar_backtest(
    fabrica: Callable[[], ModeloPronostico], corte_final: date, dir_data: Path, cfgs: Configs
) -> pd.DataFrame:
    """Predicciones de los orígenes de backtest, junto con `y`.

    Columnas: store_nbr, family, origen, fecha_objetivo, h, y y un `q…` por cuantil requerido.
    """
    cfg = cfgs.modelo
    pruebas = origenes_backtest(corte_final, cfg)
    entrenamiento = {o: origenes_entrenamiento(o, cfg) for o in pruebas}
    todos = sorted({o for lista in entrenamiento.values() for o in lista} | set(pruebas))
    datos = cargar_datos_asof(corte_final, dir_data)
    X = construir_features(datos, todos, cfg, cfgs.fuentes, con_objetivo=True)
    cuantiles = cuantiles_requeridos(cfg, cfgs.negocio)
    partes = []
    for o in pruebas:
        tr = X[X["origen"].isin(pd.to_datetime(entrenamiento[o])) & X["y"].notna()]
        te = X[X["origen"] == pd.Timestamp(o)]
        log.info("origen %s: %d filas de entrenamiento, %d de prueba", o, len(tr), len(te))
        modelo = fabrica().ajustar(tr, tr["y"])
        pred = modelo.predecir_cuantiles(te, cuantiles)
        base = te[["store_nbr", "family", "origen", "fecha_objetivo", "h", "y"]]
        partes.append(pd.concat([base, pred], axis=1))
    out = pd.concat(partes, ignore_index=True)
    out["store_nbr"] = out["store_nbr"].astype(int)
    out["family"] = out["family"].astype(str)
    return out


def guardar_backtest(
    predicciones: pd.DataFrame, modelo: str, corte_final: date, dir_data: Path, cfgs: Configs
) -> pd.DataFrame:
    """Escribe `predicciones.parquet` y `metricas.parquet` y devuelve las métricas."""
    destino = Path(dir_data) / "backtest" / modelo / f"corte={corte_final.isoformat()}"
    escribir_parquet(predicciones, destino / "predicciones.parquet")
    glob = resumen_metricas(predicciones, cfgs.negocio).assign(nivel="global", clave="")
    por_o = resumen_metricas(predicciones, cfgs.negocio, ["origen"])
    por_o = por_o.assign(nivel="origen", clave=por_o["origen"].dt.date.astype(str))
    metricas = pd.concat([glob, por_o.drop(columns="origen")], ignore_index=True)
    metricas = metricas[
        ["nivel", "clave", *[c for c in metricas.columns if c not in ("nivel", "clave")]]
    ]
    escribir_parquet(metricas, destino / "metricas.parquet")
    return metricas
