from datetime import date

import numpy as np
import pandas as pd

from reposicion.features import construir_features
from reposicion.modelos.semanal import agregar_semanal, backtest_semanal, taus_por_grupo
from reposicion.parametros import ConfigModelo, Configs
from tests.datos_modelo import datos_sinteticos, numero_dia
from tests.unit.test_backtest import NEGOCIO
from tests.unit.test_publicacion import cfg_modelo  # noqa: F401  (misma config pequeña)

CFG = ConfigModelo(cuantiles_reporte=[0.5])


def test_agregar_semanal_suma_la_cobertura(cfg_fuentes):
    origen = date(2017, 2, 6)
    X = construir_features(datos_sinteticos(), [origen], CFG, cfg_fuentes, con_objetivo=True)
    S = agregar_semanal(X, 7)
    assert len(S) == 4  # 2 tiendas × 2 familias, una fila por serie y origen
    esperado = sum(numero_dia(pd.Timestamp(origen) + pd.Timedelta(days=k)) for k in range(7))
    assert np.allclose(S["y"], esperado)  # en los datos sintéticos sales = número de día
    # la suma de la media por día de semana (4 semanas atrás) también es la de 7 días
    assert (S["media_dds_4"] > 0).all() and (S["h"] == 1).all()


def test_agregar_semanal_sin_y_si_faltan_dias(cfg_fuentes):
    # un origen cuyos 7 días no se conocen del todo: y debe ser NaN, no una suma parcial
    origen = date(2017, 3, 28)  # los datos sintéticos terminan el 2017-03-31
    X = construir_features(datos_sinteticos(), [origen], CFG, cfg_fuentes, con_objetivo=True)
    assert agregar_semanal(X, 7)["y"].isna().all()


def test_taus_por_grupo():
    assert taus_por_grupo(NEGOCIO) == {"default": 0.67}


def test_backtest_semanal_extremo_a_extremo(almacen_sin_correcciones, cfg_fuentes):
    cfg = cfg_modelo(backtest={"n_origenes": 2})
    cfgs = Configs(cfg, NEGOCIO, cfg_fuentes)
    ped = backtest_semanal(date(2017, 2, 28), almacen_sin_correcciones, cfgs)
    assert ped["origen"].nunique() == 2 and len(ped) == 2 * 6  # 3 tiendas × 2 familias
    assert (ped["pedido"] >= 0).all() and (ped["cuantil_critico"] == 0.67).all()
