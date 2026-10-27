from datetime import date, timedelta

import pandas as pd

from reposicion.backtest import (
    ejecutar_backtest,
    guardar_backtest,
    origenes_backtest,
    origenes_entrenamiento,
)
from reposicion.modelos import fabrica
from reposicion.parametros import ConfigModelo, ConfigNegocio, Configs

NEGOCIO = ConfigNegocio.model_validate({"grupos": {"default": {"c_quiebre": 1.0, "c_merma": 0.5}}})


def cfg_modelo(**cambios) -> ConfigModelo:
    base = {"cuantiles_reporte": [0.1, 0.5, 0.9], "ventana_origenes_semanas": 3}
    base.update(cambios)
    return ConfigModelo.model_validate(base)


def test_origenes_backtest_no_usan_futuro():
    cfg = ConfigModelo(cuantiles_reporte=[0.5])
    corte = date(2017, 8, 14)
    origenes = origenes_backtest(corte, cfg)
    assert len(origenes) == 8
    assert all(o.weekday() == cfg.dia_corte for o in origenes)
    # los 14 días de cada origen terminan antes del corte final: el real ya se conoce
    assert all(
        o + timedelta(days=cfg.horizonte_dias - 1) <= corte - timedelta(days=1) for o in origenes
    )
    assert origenes[-1] == date(2017, 7, 31)
    assert origenes == sorted(origenes)


def test_origenes_de_entrenamiento_terminan_antes_del_origen():
    cfg = ConfigModelo(cuantiles_reporte=[0.5])
    origen = date(2017, 7, 31)
    entrenamiento = origenes_entrenamiento(origen, cfg)
    assert len(entrenamiento) == cfg.ventana_origenes_semanas
    # el último día objetivo de todo origen de entrenamiento es anterior a `origen`
    ultimo_objetivo = max(entrenamiento) + timedelta(days=cfg.horizonte_dias - 1)
    assert ultimo_objetivo <= origen - timedelta(days=1)
    assert max(entrenamiento) == origen - timedelta(days=14)


def test_ejecutar_backtest_extremo_a_extremo(almacen_sin_correcciones, cfg_fuentes, tmp_path):
    cfg = cfg_modelo(backtest={"n_origenes": 2})
    cfgs = Configs(cfg, NEGOCIO, cfg_fuentes)
    corte = date(2017, 2, 28)
    pred = ejecutar_backtest(fabrica("baseline", cfgs), corte, almacen_sin_correcciones, cfgs)
    assert pred["origen"].nunique() == 2
    assert {"y", "q0.10", "q0.50", "q0.67", "q0.90"} <= set(pred.columns)
    assert len(pred) == 2 * 14 * 6  # 2 orígenes × 14 días × (3 tiendas × 2 familias)
    assert (pred["q0.10"] <= pred["q0.90"]).all()
    # ningún día objetivo del backtest cae después de lo que se conoce en el corte final
    assert pred["fecha_objetivo"].max() <= pd.Timestamp(corte - timedelta(days=1))

    metricas = guardar_backtest(pred, "baseline", corte, tmp_path, cfgs)
    assert metricas["nivel"].tolist() == ["global", "origen", "origen"]
    destino = tmp_path / "backtest" / "baseline" / "corte=2017-02-28"
    assert (destino / "predicciones.parquet").exists() and (destino / "metricas.parquet").exists()
