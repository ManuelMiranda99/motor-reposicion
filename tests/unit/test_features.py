from datetime import date

import pandas as pd
import pytest

from reposicion.datos import cargar_datos_asof
from reposicion.features import construir_features
from reposicion.parametros import ConfigModelo
from tests.datos_modelo import datos_sinteticos, numero_dia

O = pd.Timestamp("2017-03-13")  # lunes  # noqa: E741
CFG_MODELO = ConfigModelo(cuantiles_reporte=[0.1, 0.5, 0.9])


def _features(datos, cfg_fuentes, origen=O, con_objetivo=False):
    return construir_features(datos, [origen.date()], CFG_MODELO, cfg_fuentes, con_objetivo)


def _fila(X, tienda=1, familia="PRODUCE", h=1):
    f = X[(X["store_nbr"] == tienda) & (X["family"] == familia) & (X["h"] == h)]
    assert len(f) == 1
    return f.iloc[0]


def test_forma_y_columnas_de_id(cfg_fuentes):
    X = _features(datos_sinteticos(), cfg_fuentes)
    assert len(X) == 2 * 2 * 14
    assert (X["origen"] == O).all()
    assert list(X["h"].unique()) == list(range(1, 15))
    esperado = X["origen"] + pd.to_timedelta(X["h"] - 1, unit="D")
    assert (X["fecha_objetivo"] == esperado).all()
    assert "y" not in X.columns


def test_lags_correctos(cfg_fuentes):
    n = numero_dia(O)
    f = _fila(_features(datos_sinteticos(), cfg_fuentes), h=1)
    for k in (1, 7, 14, 28, 364):
        assert f[f"lag_{k}"] == n - k
    assert f["media_7"] == pytest.approx(n - 4)  # media de n-7..n-1
    assert f["media_28"] == pytest.approx(n - 14.5)
    assert f["mediana_28"] == pytest.approx(n - 14.5)
    assert f["prop_ceros_28"] == 0
    assert f["dias_desde_venta"] == 1


def test_media_mismo_dia_de_semana(cfg_fuentes):
    n = numero_dia(O)
    X = _features(datos_sinteticos(), cfg_fuentes)
    # h=1: lunes anteriores a O: O-7, O-14, O-21, O-28
    assert _fila(X, h=1)["media_dds_4"] == pytest.approx(n - 17.5)
    # h=3 (miércoles): O-5, O-12, O-19, O-26
    assert _fila(X, h=3)["media_dds_4"] == pytest.approx(n - 15.5)
    # h=8 es lunes otra vez: los últimos lunes conocidos son los mismos que en h=1
    assert _fila(X, h=8)["media_dds_4"] == pytest.approx(n - 17.5)
    assert _fila(X, h=8)["media_dds_8"] == pytest.approx(n - 7 * 4.5)


def test_objetivo_y(cfg_fuentes):
    X = _features(datos_sinteticos(), cfg_fuentes, con_objetivo=True)
    n = numero_dia(O)
    assert _fila(X, h=1)["y"] == n
    assert _fila(X, h=14)["y"] == n + 13


def test_features_sin_leakage(cfg_fuentes):
    """Cambiar datos que no existían en O no altera ninguna feature de O."""
    base = _features(datos_sinteticos(), cfg_fuentes)
    d = datos_sinteticos()
    d["ventas"].loc[d["ventas"]["date"] >= O, "sales"] += 999
    d["promociones"].loc[d["promociones"]["date"] > O + pd.Timedelta(days=10), "onpromotion"] = 77
    d["transacciones"].loc[
        d["transacciones"]["date"] > O - pd.Timedelta(days=3), "transactions"
    ] = 1
    d["petroleo"].loc[d["petroleo"]["date"] >= O, "dcoilwtico"] = 1.0
    pd.testing.assert_frame_equal(base, _features(d, cfg_fuentes))


def test_promociones_solo_hasta_la_anticipacion(cfg_fuentes):
    X = _features(datos_sinteticos(), cfg_fuentes)
    assert X.loc[X["h"] <= 11, "onpromotion"].notna().all()  # hasta O + 10
    assert X.loc[X["h"] >= 12, "onpromotion"].isna().all()


def test_petroleo_forward_fill_solo_hacia_adelante(cfg_fuentes):
    # O es lunes: el último dato de petróleo conocido es el del viernes anterior (O-3)
    f = _fila(_features(datos_sinteticos(), cfg_fuentes))
    viernes = O - pd.Timedelta(days=3)
    assert f["petroleo"] == pytest.approx(50 + 0.1 * (viernes - pd.Timestamp("2016-01-01")).days)


def test_feriado_local_solo_en_su_ciudad(cfg_fuentes):
    X = _features(datos_sinteticos(), cfg_fuentes)
    assert _fila(X, tienda=2, h=2)["es_feriado"] == 1  # 2017-03-14, Cuenca
    assert _fila(X, tienda=1, h=2)["es_feriado"] == 0  # Quito no lo celebra
    # el feriado nacional del 2017-03-10 aplica a ambas
    assert _fila(X, tienda=1, h=1)["dias_desde_feriado"] == 3
    assert _fila(X, tienda=2, h=1)["dias_desde_feriado"] == 3
    assert _fila(X, tienda=1, h=1)["dias_al_feriado"] == 9  # próximo para Quito: Transfer 03-22


def test_feriado_transferido(cfg_fuentes):
    X = _features(datos_sinteticos(), cfg_fuentes)
    assert _fila(X, h=8)["es_feriado"] == 0  # 2017-03-20 está transferido
    assert _fila(X, h=10)["es_feriado"] == 1  # 2017-03-22 es su Transfer


def test_puente_y_evento(cfg_fuentes):
    X = _features(datos_sinteticos(), cfg_fuentes)
    assert _fila(X, h=12)["es_puente"] == 1  # 2017-03-24
    assert _fila(X, h=13)["es_evento"] == 1  # 2017-03-25
    assert _fila(X, h=13)["es_puente"] == 0


def test_calendario(cfg_fuentes):
    X = _features(datos_sinteticos(), cfg_fuentes)
    f = _fila(X, h=3)  # miércoles 2017-03-15
    assert (f["dia_semana"], f["dia_mes"], f["mes"], f["es_quincena"]) == (2, 15, 3, 1)
    assert _fila(X, h=14)["es_quincena"] == 0


def test_serie_sin_historia_no_participa(cfg_fuentes):
    d = datos_sinteticos()
    d["ventas"] = d["ventas"][~((d["ventas"]["store_nbr"] == 2) & (d["ventas"]["date"] < O))]
    X = _features(d, cfg_fuentes)
    assert set(X["store_nbr"]) == {1}


def test_categoricas_fijas(cfg_fuentes):
    X = _features(datos_sinteticos(), cfg_fuentes)
    for c in ("store_nbr", "family", "city", "state", "type", "cluster"):
        assert isinstance(X[c].dtype, pd.CategoricalDtype)
    assert list(X["family"].cat.categories) == ["AUTOMOTIVE", "PRODUCE"]


def test_features_iguales_en_entrenamiento_e_inferencia(almacen_sin_correcciones, cfg_fuentes):
    """Las features de O desde `asof(T grande)` (entrenamiento) = desde `asof(O)` (inferencia)."""
    origen = date(2017, 2, 6)
    entrenamiento = cargar_datos_asof(date(2017, 2, 28), almacen_sin_correcciones)
    inferencia = cargar_datos_asof(origen, almacen_sin_correcciones)
    a = construir_features(entrenamiento, [origen], CFG_MODELO, cfg_fuentes, con_objetivo=True)
    b = construir_features(inferencia, [origen], CFG_MODELO, cfg_fuentes, con_objetivo=False)
    assert len(a) == len(b) > 0
    pd.testing.assert_frame_equal(
        a.drop(columns="y").reset_index(drop=True),
        b.reset_index(drop=True),
        check_categorical=False,
    )
