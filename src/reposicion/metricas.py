"""Métricas técnicas (WAPE, RMSLE, pinball, cobertura) y de negocio (newsvendor)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from reposicion.modelos.base import cuantil_de_nombre
from reposicion.parametros import ConfigNegocio

COLS_PEDIDO = ["store_nbr", "family", "origen", "grupo"]


def wape(y, pred) -> float:
    y, pred = np.asarray(y, np.float64), np.asarray(pred, np.float64)
    total = y.sum()
    return float(np.abs(y - pred).sum() / total) if total > 0 else float("nan")


def rmsle(y, pred) -> float:
    y, pred = np.asarray(y, np.float64), np.asarray(pred, np.float64)
    return float(np.sqrt(np.mean((np.log1p(pred.clip(min=0)) - np.log1p(y.clip(min=0))) ** 2)))


def pinball(y, pred_q, q: float) -> float:
    e = np.asarray(y, np.float64) - np.asarray(pred_q, np.float64)
    return float(np.mean(np.maximum(q * e, (q - 1) * e)))


def cobertura(y, bajo, alto) -> float:
    y = np.asarray(y, np.float64)
    return float(np.mean((y >= np.asarray(bajo)) & (y <= np.asarray(alto))))


def costo_newsvendor(y_cobertura, pedido, c_quiebre: float, c_merma: float) -> float:
    """Costo total: `c_quiebre` por unidad faltante + `c_merma` por unidad sobrante."""
    y, p = np.asarray(y_cobertura, np.float64), np.asarray(pedido, np.float64)
    return float(c_quiebre * np.maximum(y - p, 0).sum() + c_merma * np.maximum(p - y, 0).sum())


def fill_rate(y_cobertura, pedido) -> float:
    """Proporción de la demanda atendida con el pedido."""
    y, p = np.asarray(y_cobertura, np.float64), np.asarray(pedido, np.float64)
    return float(np.minimum(y, p).sum() / y.sum()) if y.sum() > 0 else float("nan")


def pct_merma(y_cobertura, pedido) -> float:
    """Proporción de las unidades pedidas que sobran."""
    y, p = np.asarray(y_cobertura, np.float64), np.asarray(pedido, np.float64)
    return float(np.maximum(p - y, 0).sum() / p.sum()) if p.sum() > 0 else float("nan")


def pedidos_con_real(predicciones: pd.DataFrame, cfg_negocio: ConfigNegocio) -> pd.DataFrame:
    """Pedido de cada (tienda, familia, origen) con la demanda real de su cobertura (`y_cobertura`).

    `predicciones` trae `origen`, `fecha_objetivo`, `y` y las columnas `q…`.
    """
    from reposicion.pedido import calcular_pedido

    pedido = calcular_pedido(predicciones.rename(columns={"origen": "corte"}), cfg_negocio)
    reales = predicciones.rename(columns={"origen": "corte"})
    reales = reales.merge(
        pedido[["corte", "store_nbr", "family", "cobertura_desde", "cobertura_hasta"]],
        on=["corte", "store_nbr", "family"],
    )
    dentro = (reales["fecha_objetivo"] >= reales["cobertura_desde"]) & (
        reales["fecha_objetivo"] <= reales["cobertura_hasta"]
    )
    y_cob = (
        reales[dentro]
        .groupby(["corte", "store_nbr", "family"], observed=True)["y"]
        .sum(min_count=1)
        .rename("y_cobertura")
        .reset_index()
    )
    out = pedido.merge(y_cob, on=["corte", "store_nbr", "family"], how="left")
    return out.rename(columns={"corte": "origen"})


def _metricas_filas(g: pd.DataFrame, qs: list[str]) -> dict[str, float]:
    m = {"n": float(len(g)), "wape": wape(g["y"], g["q0.50"]), "rmsle": rmsle(g["y"], g["q0.50"])}
    for c in qs:
        m[f"pinball_{c}"] = pinball(g["y"], g[c], cuantil_de_nombre(c))
    if "q0.10" in qs and "q0.90" in qs:
        m["cobertura_p10_p90"] = cobertura(g["y"], g["q0.10"], g["q0.90"])
    return m


def metricas_tecnicas(g: pd.DataFrame, qs: list[str]) -> dict[str, float]:
    """WAPE, RMSLE, pinball por cuantil y cobertura P10–P90 de `g` (con `y` y las columnas `q…`)."""
    return _metricas_filas(g, qs)


def metricas_pedido(g: pd.DataFrame, cfg_negocio: ConfigNegocio) -> dict[str, float]:
    g = g.dropna(subset=["y_cobertura"])
    if g.empty:
        return {"costo_total": float("nan"), "fill_rate": float("nan"), "pct_merma": float("nan")}
    costo = 0.0
    for nombre, sub in g.groupby("grupo"):
        grupo = cfg_negocio.grupos[nombre]
        costo += costo_newsvendor(sub["y_cobertura"], sub["pedido"], grupo.c_quiebre, grupo.c_merma)
    return {
        "costo_total": costo,
        "fill_rate": fill_rate(g["y_cobertura"], g["pedido"]),
        "pct_merma": pct_merma(g["y_cobertura"], g["pedido"]),
    }


def resumen_metricas(
    predicciones: pd.DataFrame, cfg_negocio: ConfigNegocio, por: list[str] | None = None
) -> pd.DataFrame:
    """Métricas por grupo (`por`) o globales (`por=None`).

    Solo cuentan las filas con `y` conocido. Las métricas de negocio (costo, fill rate, merma) se
    calculan sobre los pedidos y solo se llenan si `por` usa columnas del pedido
    (`store_nbr`, `family`, `origen`, `grupo`); si no, quedan en NaN.
    """
    df = predicciones.dropna(subset=["y"])
    qs = [c for c in df.columns if c.startswith("q") and c[1:2].isdigit()]
    ped = pedidos_con_real(df, cfg_negocio)
    df = df.assign(store_nbr=df["store_nbr"].astype(int), family=df["family"].astype(str)).merge(
        ped[COLS_PEDIDO], on=["store_nbr", "family", "origen"], how="left"
    )
    por = por or []
    claves_df = df.groupby(por, observed=True) if por else [((), df)]
    filas = []
    for clave, g in claves_df:
        fila = dict(zip(por, clave if isinstance(clave, tuple) else (clave,), strict=True))
        fila.update(_metricas_filas(g, qs))
        if all(c in COLS_PEDIDO for c in por):
            sel = pd.Series(True, index=ped.index)
            for c, v in zip(por, clave if isinstance(clave, tuple) else (clave,), strict=True):
                sel &= ped[c] == v
            fila.update(metricas_pedido(ped[sel], cfg_negocio))
        filas.append(fila)
    return pd.DataFrame(filas)
