import numpy as np
import pandas as pd
import pytest

from reposicion.features import construir_features
from reposicion.modelos import fabrica
from reposicion.modelos.base import aplicar_regla_ceros
from reposicion.modelos.lgbm import LightGBMCuantiles
from reposicion.parametros import ConfigModelo, ConfigNegocio, Configs
from tests.datos_modelo import datos_sinteticos

CFG = ConfigModelo.model_validate(
    {
        "cuantiles_reporte": [0.1, 0.5, 0.9],
        "lightgbm": {
            "num_boost_round": 15,
            "num_leaves": 7,
            "min_data_in_leaf": 5,
            "num_threads": 2,
        },
    }
)
QS = [0.1, 0.5, 0.9]
ORIGENES = [pd.Timestamp("2017-01-02") + pd.Timedelta(days=7 * k) for k in range(8)]


@pytest.fixture(scope="module")
def X(cfg_fuentes):
    X = construir_features(
        datos_sinteticos(), [o.date() for o in ORIGENES], CFG, cfg_fuentes, con_objetivo=True
    )
    rng = np.random.default_rng(0)
    X["y"] = (X["y"] + rng.normal(0, 3, len(X))).clip(lower=0)  # ruido: hay dispersión de cuantiles
    return X[X["y"].notna()].reset_index(drop=True)


@pytest.fixture(scope="module")
def modelo(X):
    return LightGBMCuantiles(CFG, QS).ajustar(X, X["y"])


def test_lgbm_determinista(X, modelo):
    otro = LightGBMCuantiles(CFG, QS).ajustar(X, X["y"])
    pd.testing.assert_frame_equal(
        modelo.predecir_cuantiles(X, QS), otro.predecir_cuantiles(X, QS), check_exact=True
    )


def test_lgbm_cuantiles_monotonos_y_no_negativos(X, modelo):
    pred = modelo.predecir_cuantiles(X, QS)
    assert list(pred.columns) == ["q0.10", "q0.50", "q0.90"]
    assert (pred.to_numpy() >= 0).all() and not pred.isna().to_numpy().any()
    assert (np.diff(pred.to_numpy(), axis=1) >= 0).all()
    assert pred.index.equals(X.index)


def test_lgbm_guardar_cargar_misma_prediccion(X, modelo, tmp_path):
    modelo.guardar(tmp_path / "m")
    assert (tmp_path / "m" / "meta.json").exists()
    assert (tmp_path / "m" / "modelo_0.50.txt").exists()
    assert not list((tmp_path / "m").glob("*.tmp"))
    cargado = LightGBMCuantiles.cargar(tmp_path / "m")
    pd.testing.assert_frame_equal(
        modelo.predecir_cuantiles(X, QS), cargado.predecir_cuantiles(X, QS), check_exact=True
    )


def test_categorias_fijas(X, modelo):
    sub = X[X["store_nbr"] == 2]
    completa = modelo._matriz(X)
    parcial = modelo._matriz(sub)
    for c in ("store_nbr", "family", "city"):
        assert parcial[c].cat.categories.tolist() == completa[c].cat.categories.tolist()
        assert parcial[c].cat.codes.tolist() == completa.loc[sub.index, c].cat.codes.tolist()
    # y la predicción de un subconjunto coincide con la de esas mismas filas en el conjunto
    pd.testing.assert_frame_equal(
        modelo.predecir_cuantiles(sub, QS),
        modelo.predecir_cuantiles(X, QS).loc[sub.index],
        check_exact=True,
    )


def test_categoria_desconocida_no_falla(X, modelo):
    nuevo = X.head(20).copy()
    nuevo["store_nbr"] = pd.Categorical([99] * len(nuevo), categories=[99])
    pred = modelo.predecir_cuantiles(nuevo, QS)
    assert not pred.isna().to_numpy().any()


def test_regla_de_ceros_compartida_con_el_baseline(X, modelo):
    quieto = X.head(30).copy()
    quieto["dias_desde_venta"] = CFG.regla_ceros.dias_sin_ventas + 1
    assert (modelo.predecir_cuantiles(quieto, QS).to_numpy() == 0).all()
    v = np.arange(3.0)
    solo = pd.DataFrame({"dias_desde_venta": [1, 100, 1]})
    assert aplicar_regla_ceros(v, solo, 56).tolist() == [0.0, 0.0, 2.0][:1] + [0.0, 2.0]


def test_cuantil_no_entrenado_falla(X, modelo):
    with pytest.raises(ValueError, match="cuantil"):
        modelo.predecir_cuantiles(X.head(5), [0.33])


def test_fabrica_lgbm_entrena_los_cuantiles_del_negocio(cfg_fuentes):
    negocio = ConfigNegocio.model_validate(
        {"grupos": {"default": {"c_quiebre": 1.0, "c_merma": 0.5}}}
    )
    m = fabrica("lgbm", Configs(CFG, negocio, cfg_fuentes))()
    assert m.cuantiles_entrenados == [0.1, 0.5, 0.67, 0.9]
