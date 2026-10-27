import numpy as np
import pandas as pd
import pytest

from reposicion.features import construir_features
from reposicion.modelos.base import (
    cuantiles_requeridos,
    nombre_cuantil,
    ordenar_cuantiles,
)
from reposicion.modelos.baseline import Baseline
from reposicion.parametros import ConfigModelo, ConfigNegocio
from tests.datos_modelo import datos_sinteticos

CFG = ConfigModelo(cuantiles_reporte=[0.1, 0.5, 0.9])
ORIGENES = [pd.Timestamp("2017-01-02") + pd.Timedelta(days=7 * k) for k in range(8)]


@pytest.fixture(scope="module")
def X(cfg_fuentes):
    return construir_features(
        datos_sinteticos(), [o.date() for o in ORIGENES], CFG, cfg_fuentes, con_objetivo=True
    )


def test_nombre_cuantil():
    assert nombre_cuantil(0.1) == "q0.10"
    assert nombre_cuantil(0.4) == "q0.40"
    assert nombre_cuantil(0.91) == "q0.91"


def test_cuantiles_requeridos_incluye_taus(cfg_fuentes):
    negocio = ConfigNegocio(
        grupos={
            "peres": {"c_quiebre": 1.0, "c_merma": 1.5, "familias": ["PRODUCE"]},
            "default": {"c_quiebre": 1.0, "c_merma": 0.5},
        }
    )
    assert cuantiles_requeridos(CFG, negocio) == [0.1, 0.4, 0.5, 0.67, 0.9]


def test_ordenar_cuantiles():
    df = pd.DataFrame({"q0.10": [5.0, 1.0], "q0.50": [3.0, 2.0], "q0.90": [4.0, 3.0]})
    out = ordenar_cuantiles(df)
    assert out.to_numpy().tolist() == [[3.0, 4.0, 5.0], [1.0, 2.0, 3.0]]


def test_baseline_cuantiles_monotonos_y_no_negativos(X):
    rng = np.random.default_rng(0)
    y = X["y"] + rng.normal(0, 5, len(X))  # ruido para que haya residuos
    modelo = Baseline(CFG).ajustar(X, y)
    pred = modelo.predecir_cuantiles(X, [0.1, 0.5, 0.9, 0.97])
    assert list(pred.columns) == ["q0.10", "q0.50", "q0.90", "q0.97"]
    assert (pred.to_numpy() >= 0).all()
    assert (np.diff(pred.to_numpy(), axis=1) >= 0).all()
    assert pred.index.equals(X.index)


def test_baseline_sin_residuos_devuelve_el_punto(X):
    # serie perfectamente predecible: y == media_dds_4 → los cuantiles son el punto
    y = X["media_dds_4"].astype("float64")
    pred = Baseline(CFG).ajustar(X, y).predecir_cuantiles(X, [0.5])
    np.testing.assert_allclose(pred["q0.50"], y.clip(lower=0), rtol=1e-5)


def test_regla_ceros(X):
    modelo = Baseline(CFG).ajustar(X, X["y"])
    parado = X.copy()
    parado["dias_desde_venta"] = 57.0
    activo = X.copy()
    activo["dias_desde_venta"] = 56.0
    assert (modelo.predecir_cuantiles(parado, [0.1, 0.5, 0.9]).to_numpy() == 0).all()
    assert (modelo.predecir_cuantiles(activo, [0.5])["q0.50"] > 0).all()


def test_ajustar_ignora_y_desconocida(X):
    y = X["y"].copy()
    y.iloc[:10] = np.nan
    pred = Baseline(CFG).ajustar(X, y).predecir_cuantiles(X, [0.5])
    assert pred["q0.50"].notna().all()


def test_familia_desconocida_usa_el_residuo_global(X):
    modelo = Baseline(CFG).ajustar(
        X[X["family"] == "PRODUCE"], X.loc[X["family"] == "PRODUCE", "y"]
    )
    pred = modelo.predecir_cuantiles(X[X["family"] == "AUTOMOTIVE"], [0.5])
    assert pred["q0.50"].notna().all()


def test_guardar_y_cargar(X, tmp_path):
    modelo = Baseline(CFG).ajustar(X, X["y"] + 3)
    modelo.guardar(tmp_path / "m")
    assert [p.name for p in (tmp_path / "m").iterdir()] == ["baseline.json"]  # sin pickle
    cargado = Baseline.cargar(tmp_path / "m")
    qs = [0.1, 0.5, 0.9]
    pd.testing.assert_frame_equal(
        modelo.predecir_cuantiles(X, qs), cargado.predecir_cuantiles(X, qs)
    )
