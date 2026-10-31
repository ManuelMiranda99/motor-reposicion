"""Variante "cuantil de la demanda semanal" para el pedido (evaluación, fase 5).

Alternativa a sumar los cuantiles diarios τ: un modelo LightGBM con objetivo = suma de las ventas
de la cobertura (7 días) y una fila por (serie, origen). Se entrena un cuantil por grupo de costos
(solo los τ del negocio). Las features son las del origen (h = 1) más agregados de la semana
objetivo (suma de la media por día de semana, de las promociones y de los flags de feriado).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from reposicion.backtest import origenes_backtest, origenes_entrenamiento
from reposicion.datos import cargar_datos_asof
from reposicion.features import construir_features
from reposicion.modelos.base import nombre_cuantil
from reposicion.modelos.lgbm import LightGBMCuantiles
from reposicion.parametros import ConfigLightGBM, ConfigNegocio, Configs
from reposicion.pedido import cuantil_critico, grupo_de_familia

SUMAS = ["media_dds_4", "media_dds_8", "onpromotion", "es_feriado", "es_puente",
         "es_dia_laboral_extra", "es_evento", "es_quincena"]  # fmt: skip
LLAVE = ["store_nbr", "family", "origen"]


def agregar_semanal(X: pd.DataFrame, cobertura_dias: int) -> pd.DataFrame:
    """Una fila por (serie, origen): features del origen + agregados de los días de la cobertura.

    `y` es la suma de la cobertura y solo existe si se conocen los `cobertura_dias` días.
    """
    ventana = X[X["h"] <= cobertura_dias]
    base = ventana[ventana["h"] == 1].reset_index(drop=True)
    g = ventana.groupby(LLAVE, observed=True, sort=True)
    sumas = g[SUMAS].sum(min_count=1).reset_index()
    base = base.drop(columns=SUMAS).merge(sumas, on=LLAVE, how="left")
    if "y" in ventana.columns:
        conocidos = g["y"].count().reset_index(name="n_y")
        y = g["y"].sum(min_count=1).reset_index()
        y = y.merge(conocidos, on=LLAVE)
        y.loc[y["n_y"] < cobertura_dias, "y"] = np.nan
        base = base.drop(columns="y").merge(y[[*LLAVE, "y"]], on=LLAVE, how="left")
    return base


def taus_por_grupo(cfg_negocio: ConfigNegocio) -> dict[str, float]:
    return {n: cuantil_critico(g.c_quiebre, g.c_merma) for n, g in cfg_negocio.grupos.items()}


def cfg_lgbm_semanal(cfgs: Configs) -> ConfigLightGBM:
    return ConfigLightGBM.model_validate(
        {**cfgs.modelo.lightgbm.model_dump(), **cfgs.modelo.lightgbm_semanal.model_dump()}
    )


def pedido_semanal(modelo: LightGBMCuantiles, S: pd.DataFrame, cfg_negocio: ConfigNegocio):
    """Pedido (entero) de cada fila de `S`: cuantil τ del grupo de la demanda semanal."""
    taus = taus_por_grupo(cfg_negocio)
    q = modelo.predecir_cuantiles(S, sorted(set(taus.values())))
    grupo = S["family"].astype(str).map(lambda f: grupo_de_familia(f, cfg_negocio))
    tau = grupo.map(taus)
    demanda = np.zeros(len(S))
    for t in sorted(set(taus.values())):
        sel = (tau == t).to_numpy()
        demanda[sel] = q.loc[S.index[sel], nombre_cuantil(t)].to_numpy()
    faltante = np.maximum(demanda - cfg_negocio.inventario_inicial, 0).round(6)
    redondeo = np.ceil if cfg_negocio.redondeo == "entero_arriba" else np.rint
    return pd.DataFrame(
        {
            "store_nbr": S["store_nbr"].astype(int).to_numpy(),
            "family": S["family"].astype(str).to_numpy(),
            "origen": S["origen"].to_numpy(),
            "grupo": grupo.to_numpy(),
            "cuantil_critico": tau.to_numpy(),
            "demanda_cuantil": demanda,
            "pedido": redondeo(faltante).astype(np.int64),
        }
    )


def backtest_semanal(corte_final: date, dir_data: Path, cfgs: Configs) -> pd.DataFrame:
    """Pedidos de la variante semanal en los mismos orígenes y ventanas que el backtest diario."""
    cfg = cfgs.modelo
    pruebas = origenes_backtest(corte_final, cfg)
    entrenamiento = {o: origenes_entrenamiento(o, cfg) for o in pruebas}
    todos = sorted({o for lista in entrenamiento.values() for o in lista} | set(pruebas))
    datos = cargar_datos_asof(corte_final, dir_data)
    X = construir_features(datos, todos, cfg, cfgs.fuentes, con_objetivo=True)
    S = agregar_semanal(X, cfgs.negocio.cobertura_dias)
    taus = sorted(set(taus_por_grupo(cfgs.negocio).values()))
    partes = []
    for o in pruebas:
        tr = S[S["origen"].isin(pd.to_datetime(entrenamiento[o])) & S["y"].notna()]
        te = S[S["origen"] == pd.Timestamp(o)]
        modelo = LightGBMCuantiles(cfg, taus, cfg_lgbm_semanal(cfgs)).ajustar(tr, tr["y"])
        partes.append(pedido_semanal(modelo, te, cfgs.negocio))
    return pd.concat(partes, ignore_index=True)
