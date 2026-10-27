"""Pedido sugerido por tienda × familia (newsvendor sobre la demanda de la cobertura)."""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from reposicion.modelos.base import cuantil_de_nombre, nombre_cuantil
from reposicion.parametros import ConfigNegocio

log = logging.getLogger(__name__)


def cuantil_critico(c_quiebre: float, c_merma: float) -> float:
    """τ = c_quiebre / (c_quiebre + c_merma), redondeado a 2 decimales.

    El redondeo hace que el modelo se entrene exactamente en el cuantil que usa el pedido.
    """
    return round(c_quiebre / (c_quiebre + c_merma), 2)


def grupo_de_familia(family: str, cfg_negocio: ConfigNegocio) -> str:
    for nombre, grupo in cfg_negocio.grupos.items():
        if family in grupo.familias:
            return nombre
    return "default"


def _valor_cuantil(df: pd.DataFrame, tau: float) -> np.ndarray:
    """Valores del cuantil τ; si no es una columna, interpola entre los vecinos."""
    nombre = nombre_cuantil(tau)
    if nombre in df.columns:
        return df[nombre].to_numpy(np.float64)
    disponibles = sorted((cuantil_de_nombre(c), c) for c in df.columns if c[1:2].isdigit())
    qs = [q for q, _ in disponibles]
    log.warning("el cuantil %s no está en el pronóstico: se interpola entre %s", nombre, qs)
    if tau <= qs[0]:
        return df[disponibles[0][1]].to_numpy(np.float64)
    if tau >= qs[-1]:
        return df[disponibles[-1][1]].to_numpy(np.float64)
    k = int(np.searchsorted(qs, tau))
    (q0, c0), (q1, c1) = disponibles[k - 1], disponibles[k]
    w = (tau - q0) / (q1 - q0)
    return (1 - w) * df[c0].to_numpy(np.float64) + w * df[c1].to_numpy(np.float64)


def calcular_pedido(pronostico: pd.DataFrame, cfg_negocio: ConfigNegocio) -> pd.DataFrame:
    """Pedido de cada (corte, tienda, familia).

    `pronostico` trae `corte`, `store_nbr`, `family`, `fecha_objetivo` y columnas `q…`. La
    demanda de la cobertura es la suma de los cuantiles diarios τ (dependencia perfecta entre
    días: supuesto conservador).
    """
    p = pronostico.copy()
    p["store_nbr"] = p["store_nbr"].astype(int)
    p["family"] = p["family"].astype(str)
    p["grupo"] = p["family"].map(lambda f: grupo_de_familia(f, cfg_negocio))
    desde = p["corte"] + pd.Timedelta(days=cfg_negocio.lead_time_dias)
    hasta = desde + pd.Timedelta(days=cfg_negocio.cobertura_dias - 1)
    p["cobertura_desde"], p["cobertura_hasta"] = desde, hasta
    p = p[(p["fecha_objetivo"] >= desde) & (p["fecha_objetivo"] <= hasta)].copy()
    p["cuantil_critico"] = 0.0
    p["demanda_dia"] = 0.0
    for nombre, grupo in cfg_negocio.grupos.items():
        sel = (p["grupo"] == nombre).to_numpy()
        if not sel.any():
            continue
        tau = cuantil_critico(grupo.c_quiebre, grupo.c_merma)
        p.loc[sel, "cuantil_critico"] = tau
        p.loc[sel, "demanda_dia"] = _valor_cuantil(p[sel], tau)
    llaves = ["corte", "store_nbr", "family", "grupo", "cuantil_critico",
              "cobertura_desde", "cobertura_hasta"]  # fmt: skip
    ped = p.groupby(llaves, observed=True, sort=True)["demanda_dia"].sum().reset_index()
    ped = ped.rename(columns={"demanda_dia": "demanda_cuantil"})
    ped["inventario_inicial"] = float(cfg_negocio.inventario_inicial)
    faltante = (ped["demanda_cuantil"] - ped["inventario_inicial"]).clip(lower=0).round(6)
    redondeo = np.ceil if cfg_negocio.redondeo == "entero_arriba" else np.rint
    ped["pedido"] = redondeo(faltante).astype(np.int64)
    return ped
