"""Comparación baseline vs LightGBM (y variante semanal) → `reports/comparacion_modelos.md`.

El reporte no lleva marcas de tiempo: regenerarlo con los mismos datos produce el mismo texto.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import date
from pathlib import Path

import pandas as pd

from reposicion.backtest import ejecutar_backtest, guardar_backtest, origenes_backtest
from reposicion.io import escribir_parquet
from reposicion.metricas import metricas_pedido, pedidos_con_real, resumen_metricas
from reposicion.modelos import fabrica
from reposicion.modelos.semanal import backtest_semanal
from reposicion.parametros import Configs
from reposicion.registro import Decision, evaluar_promocion, resumir_evaluacion

log = logging.getLogger(__name__)


def _tabla(df: pd.DataFrame, formatos: dict[str, str] | None = None) -> str:
    """DataFrame → tabla markdown (sin depender de `tabulate`)."""
    formatos = formatos or {}
    cab = "| " + " | ".join(df.columns) + " |"
    sep = "|" + "|".join("---" for _ in df.columns) + "|"
    filas = []
    for _, r in df.iterrows():
        celdas = []
        for c in df.columns:
            v = r[c]
            f = formatos.get(c)
            celdas.append(format(v, f) if f and not isinstance(v, str) else str(v))
        filas.append("| " + " | ".join(celdas) + " |")
    return "\n".join([cab, sep, *filas])


def _delta(a: float, b: float) -> float:
    return (b - a) / a if a else float("nan")


LLAVE = ["store_nbr", "family", "origen"]


def pedidos_completos(pred: pd.DataFrame, cfg_negocio) -> pd.DataFrame:
    """Pedidos diarios con la demanda real de **todos** los días de su cobertura conocida.

    La variante semanal compara contra la suma de la cobertura; si falta un día real (p. ej. el
    faltante del 2017-07-04) el costo sería incomparable, así que ese pedido no cuenta.
    """
    cob, lt = cfg_negocio.cobertura_dias, cfg_negocio.lead_time_dias
    en_cobertura = (pred["h"] > lt) & (pred["h"] <= lt + cob) & pred["y"].notna()
    n = pred[en_cobertura].groupby(LLAVE, observed=True).size().rename("n_conocidos").reset_index()
    n["store_nbr"], n["family"] = n["store_nbr"].astype(int), n["family"].astype(str)
    ped = pedidos_con_real(pred, cfg_negocio).merge(n, on=LLAVE, how="left")
    return ped[ped["n_conocidos"] == cob].drop(columns="n_conocidos").reset_index(drop=True)


def metricas_variante_semanal(pred_lgbm: pd.DataFrame, pedidos_sem: pd.DataFrame, cfgs: Configs):
    """Pedido semanal vs. diario (LightGBM) sobre las mismas series y orígenes completos."""
    base = pedidos_completos(pred_lgbm, cfgs.negocio)
    sem = base[LLAVE + ["y_cobertura"]].merge(pedidos_sem, on=LLAVE, how="left")
    if sem["pedido"].isna().any():
        raise ValueError("la variante semanal no cubre las mismas series y orígenes")
    return base, sem


def comparar_modelos(
    corte: date, dir_data: Path, cfgs: Configs, dir_reportes: Path
) -> tuple[Path, Decision]:
    """Backtest de baseline, LightGBM y variante semanal; escribe el reporte (devuelve su ruta)."""
    dir_data = Path(dir_data)
    tiempos: dict[str, float] = {}
    preds: dict[str, pd.DataFrame] = {}
    for tipo in ("baseline", "lgbm"):
        t0 = time.perf_counter()
        preds[tipo] = ejecutar_backtest(fabrica(tipo, cfgs), corte, dir_data, cfgs)
        guardar_backtest(preds[tipo], tipo, corte, dir_data, cfgs)
        tiempos[tipo] = time.perf_counter() - t0
        log.info("backtest %s: %.0f s", tipo, tiempos[tipo])
    t0 = time.perf_counter()
    pedidos_sem = backtest_semanal(corte, dir_data, cfgs)
    tiempos["lgbm_semanal"] = time.perf_counter() - t0
    log.info("backtest semanal: %.0f s", tiempos["lgbm_semanal"])
    escribir_parquet(
        pedidos_sem,
        dir_data / "backtest" / "lgbm_semanal" / f"corte={corte.isoformat()}" / "pedidos.parquet",
    )

    res = {t: resumir_evaluacion(p, cfgs.negocio) for t, p in preds.items()}
    decision = evaluar_promocion(res["lgbm"], res["baseline"], cfgs.promocion)
    texto = _redactar(corte, cfgs, preds, pedidos_sem, decision)
    log.info("tiempos de ejecución (s): %s", {k: round(v) for k, v in tiempos.items()})
    dir_reportes = Path(dir_reportes)
    dir_reportes.mkdir(parents=True, exist_ok=True)
    destino = dir_reportes / "comparacion_modelos.md"
    tmp = destino.with_name(destino.name + ".tmp")
    tmp.write_text(texto, encoding="utf-8")
    os.replace(tmp, destino)
    return destino, decision


def _redactar(
    corte: date,
    cfgs: Configs,
    preds: dict[str, pd.DataFrame],
    pedidos_sem: pd.DataFrame,
    decision: Decision,
) -> str:
    neg = cfgs.negocio
    origenes = origenes_backtest(corte, cfgs.modelo)
    pb, pl = preds["baseline"], preds["lgbm"]
    gb = resumen_metricas(pb, neg).iloc[0]
    gl = resumen_metricas(pl, neg).iloc[0]

    L: list[str] = []
    L.append(f"# Comparación de modelos — corte {corte.isoformat()}\n")
    L.append(
        f"Backtest rolling-origin con {len(origenes)} orígenes semanales "
        f"({origenes[0]} a {origenes[-1]}), misma ventana de entrenamiento "
        f"({cfgs.modelo.ventana_origenes_semanas} semanas) y mismos datos para ambos modelos. "
        f"Datos revisados a la fecha del corte (ver DECISIONES §8). {len(pl):,} predicciones "
        "diarias por modelo.\n"
    )

    # ---- global
    filas = [
        ("WAPE (mediana)", gb["wape"], gl["wape"], ".4f"),
        ("RMSLE (mediana)", gb["rmsle"], gl["rmsle"], ".4f"),
        ("Pinball q0.50", gb["pinball_q0.50"], gl["pinball_q0.50"], ".3f"),
        ("Pinball q0.90", gb["pinball_q0.90"], gl["pinball_q0.90"], ".3f"),
        ("Cobertura P10-P90", gb["cobertura_p10_p90"], gl["cobertura_p10_p90"], ".4f"),
        ("Costo de negocio total", gb["costo_total"], gl["costo_total"], ",.0f"),
        ("Fill rate", gb["fill_rate"], gl["fill_rate"], ".4f"),
        ("Merma (% de lo pedido)", gb["pct_merma"], gl["pct_merma"], ".4f"),
    ]
    t = pd.DataFrame(
        {
            "Métrica": [f[0] for f in filas],
            "Baseline": [format(f[1], f[3]) for f in filas],
            "LightGBM": [format(f[2], f[3]) for f in filas],
            "Cambio relativo": [f"{_delta(f[1], f[2]):+.1%}" for f in filas],
        }
    )
    L.append("## Métricas globales\n\n" + _tabla(t) + "\n")

    # ---- decisión
    L.append("## Decisión de promoción (LightGBM como challenger del baseline)\n")
    L.append(f"**{'PROMOVER' if decision.promover else 'NO PROMOVER'}**\n")
    L.extend(f"- {m}" for m in decision.motivos)
    L.append("")

    # ---- por familia
    fb = resumen_metricas(pb, neg, ["family"]).set_index("family")
    fl = resumen_metricas(pl, neg, ["family"]).set_index("family")
    vol = pl.dropna(subset=["y"]).groupby(pl["family"].astype(str))["y"].sum()
    tf = pd.DataFrame(
        {
            "Familia": fb.index,
            "% volumen": (vol.reindex(fb.index) / vol.sum()).to_numpy(),
            "WAPE base": fb["wape"].to_numpy(),
            "WAPE LGBM": fl["wape"].reindex(fb.index).to_numpy(),
            "Costo base": fb["costo_total"].to_numpy(),
            "Costo LGBM": fl["costo_total"].reindex(fb.index).to_numpy(),
        }
    )
    tf["Δ costo"] = (tf["Costo LGBM"] - tf["Costo base"]) / tf["Costo base"]
    tf = tf.sort_values("% volumen", ascending=False)
    L.append(
        "## Por familia (ordenadas por volumen)\n\n"
        + _tabla(
            tf,
            {
                "% volumen": ".1%",
                "WAPE base": ".3f",
                "WAPE LGBM": ".3f",
                "Costo base": ",.0f",
                "Costo LGBM": ",.0f",
                "Δ costo": "+.1%",
            },
        )  # fmt: skip
        + "\n"
    )

    # ---- por h
    hb = resumen_metricas(pb, neg, ["h"]).set_index("h")
    hl = resumen_metricas(pl, neg, ["h"]).set_index("h")
    th = pd.DataFrame(
        {
            "h": hb.index.astype(int),
            "WAPE base": hb["wape"].to_numpy(),
            "WAPE LGBM": hl["wape"].to_numpy(),
            "Cobertura base": hb["cobertura_p10_p90"].to_numpy(),
            "Cobertura LGBM": hl["cobertura_p10_p90"].to_numpy(),
        }
    )
    L.append(
        "## Por horizonte (h = días desde el corte)\n\n"
        + _tabla(th, {c: ".4f" for c in th.columns if c != "h"})
        + "\n"
    )

    # ---- variante semanal
    pedidos_l, sem = metricas_variante_semanal(pl, pedidos_sem, cfgs)
    variantes = {
        "Baseline, suma de cuantiles diarios": pedidos_completos(pb, neg),
        "LightGBM, suma de cuantiles diarios (actual)": pedidos_l,
        "LightGBM, cuantil de la demanda semanal": sem,
    }
    filas = []
    for nombre, ped in variantes.items():
        m = metricas_pedido(ped, neg)
        fila = {"Pedido": nombre, "Costo total": m["costo_total"], "Fill rate": m["fill_rate"],
                "Merma": m["pct_merma"]}  # fmt: skip
        for g in neg.grupos:
            fila[f"Costo {g}"] = metricas_pedido(ped[ped["grupo"] == g], neg)["costo_total"]
        filas.append(fila)
    tv = pd.DataFrame(filas)
    base_costo = tv.loc[1, "Costo total"]
    tv["Δ costo vs LGBM diario"] = (tv["Costo total"] - base_costo) / base_costo
    fm = {
        "Costo total": ",.0f",
        "Fill rate": ".4f",
        "Merma": ".4f",
        "Δ costo vs LGBM diario": "+.1%",
    }
    fm.update({f"Costo {g}": ",.0f" for g in neg.grupos})
    L.append(
        "## Variante: cuantil de la demanda semanal para el pedido\n\n"
        "Un modelo LightGBM con objetivo = suma de los 7 días de la cobertura (una fila por "
        "serie y origen; un cuantil por grupo de costos), contra el pedido por suma de cuantiles "
        "diarios. "
        "Mismos orígenes, mismas series y misma demanda real; solo cuentan los pedidos cuyos 7 "
        "días reales se conocen (por eso el costo total difiere del de la tabla global, que "
        "descarta los días sin dato real). Un costo menor es mejor.\n\n" + _tabla(tv, fm) + "\n"
    )
    return "\n".join(L)
