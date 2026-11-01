"""Revisión independiente — features, modelo, pedido, registro/reproducción y configuración.

Cada prueba afirma el comportamiento CORRECTO esperado; si falla, demuestra el hallazgo descrito en
`tests/revision/INFORME.md`.
"""

from __future__ import annotations

import json
import shutil
from datetime import date

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from reposicion.entrenamiento import entrenar_modelo
from reposicion.features import construir_features
from reposicion.fuentes import cargar_fuentes
from reposicion.modelos.base import cuantiles_requeridos
from reposicion.parametros import ConfigModelo, ConfigNegocio, ConfigPromocion, Configs
from reposicion.publicacion import pronosticar_corte
from reposicion.registro import (
    Decision,
    ResumenEvaluacion,
    anotar_decision,
    checks_tecnicos,
    evaluar_promocion,
    registrar,
)
from reposicion.reproduccion import reproducir
from tests.conftest import RAIZ
from tests.datos_modelo import datos_sinteticos
from tests.revision.comun import configs

FUENTES = cargar_fuentes(RAIZ / "config" / "sources.yaml")


# ----------------------------------------- H-MOD-1 serie nueva tratada como "muerta" (tienda 52)
def test_serie_nueva_no_se_trata_como_serie_sin_ventas_hace_un_anio():
    """Una tienda que entra al maestro con filas en 0 antes de abrir (la 52: filas desde el 04-13,
    primera venta el 04-20) es "activa" en el corte siguiente, pero `dias_desde_venta` vale 365
    (= ventana + 1) aunque la serie existe hace 4 días. La regla de ceros (> 56 días) fuerza
    pronóstico y pedido 0 en su semana de apertura (dato real: corte 2017-04-17, pedido 0 para la
    tienda 52 contra 114,797 unidades vendidas en esa cobertura)."""
    datos = datos_sinteticos()
    datos["tiendas"] = pd.concat(
        [datos["tiendas"], pd.DataFrame([(3, "Quito", "Pichincha", "A", 3)],
                                        columns=datos["tiendas"].columns)],
        ignore_index=True,
    )  # fmt: skip
    nuevas = pd.DataFrame(
        [(f, 3, fam, 0.0) for f in pd.date_range("2017-03-02", "2017-03-05")
         for fam in ("PRODUCE", "AUTOMOTIVE")],
        columns=["date", "store_nbr", "family", "sales"],
    )  # fmt: skip
    datos["ventas"] = pd.concat([datos["ventas"], nuevas], ignore_index=True)
    X = construir_features(
        datos, [date(2017, 3, 6)], ConfigModelo(cuantiles_reporte=[0.5]), FUENTES, False
    )
    t3 = X[X["store_nbr"].astype(int) == 3]
    assert len(t3) > 0
    edad = 4  # días con fila antes del corte
    assert (t3["dias_desde_venta"] <= edad + 1).all(), (
        f"dias_desde_venta={t3['dias_desde_venta'].iloc[0]:.0f} para una serie con {edad} días"
    )


# --------------------------------------------------- H-CFG-1 cobertura fuera del horizonte
def test_cobertura_mas_lead_time_mayor_que_el_horizonte_no_se_trunca_en_silencio():
    """`lead_time_dias + cobertura_dias > horizonte_dias` se rechaza al armar `Configs` (y por
    tanto al cargar la configuración), con un error claro."""
    negocio = ConfigNegocio.model_validate(
        {"lead_time_dias": 10, "cobertura_dias": 7,
         "grupos": {"default": {"c_quiebre": 1.0, "c_merma": 0.5}}}
    )  # fmt: skip
    modelo = ConfigModelo(cuantiles_reporte=[0.5])
    with pytest.raises(ValueError, match="horizonte"):
        Configs(modelo, negocio, None)  # type: ignore[arg-type]


# --------------------------------------------------- H-CFG-2 τ que redondea a 0 o a 1
def test_tau_redondeado_queda_dentro_de_0_1():
    """`cuantil_critico` redondea a 2 decimales: con c_merma = 0.004 τ = 0.996 → 1.0. La
    configuración se acepta y `cuantiles_requeridos` incluye 1.0 (LightGBM con `alpha=1` y un
    cuantil 1.0 no tienen sentido; los cuantiles de reporte sí se validan en (0, 1))."""
    with pytest.raises(ValidationError, match="τ"):
        ConfigNegocio.model_validate({"grupos": {"default": {"c_quiebre": 1.0, "c_merma": 0.004}}})
    with pytest.raises(ValidationError, match="τ"):
        ConfigNegocio.model_validate({"grupos": {"default": {"c_quiebre": 0.004, "c_merma": 1.0}}})
    negocio = ConfigNegocio.model_validate(
        {"grupos": {"default": {"c_quiebre": 1.0, "c_merma": 0.5}}}
    )
    qs = cuantiles_requeridos(ConfigModelo(cuantiles_reporte=[0.1, 0.5, 0.9]), negocio)
    assert all(0 < q < 1 for q in qs), qs


# --------------------------------------------------- H-CFG-3 q0.50 obligatorio pero no validado
def test_cuantiles_reporte_sin_mediana_se_rechaza():
    """WAPE, RMSLE, sesgo y el seguimiento leen la columna `q0.50` sin comprobarla, pero
    `ConfigModelo` acepta `cuantiles_reporte: [0.1, 0.9]`; el error aparece tarde (`KeyError`
    en el backtest o el seguimiento)."""
    with pytest.raises(ValidationError):
        ConfigModelo(cuantiles_reporte=[0.1, 0.9])


# ------------------------------------------- H-PRO-1 checks técnicos sin "filas completas"
def _pred(n_series: int = 2) -> pd.DataFrame:
    filas = [
        {"store_nbr": s, "family": "A", "origen": pd.Timestamp("2017-01-02"), "h": h,
         "q0.10": 1.0, "q0.50": 2.0, "q0.90": 3.0}
        for s in range(1, n_series + 1) for h in range(1, 15)
    ]  # fmt: skip
    return pd.DataFrame(filas)


def test_checks_tecnicos_detectan_filas_faltantes():
    """`promotion.yaml` documenta `checks_tecnicos: ... filas completas`, pero `checks_tecnicos` no
    verifica que estén todas las (serie, origen, h): un challenger al que le faltan series pasa."""
    pred = _pred().iloc[:-10]  # faltan 10 horizontes de la serie 2
    assert checks_tecnicos(pred) != []


def test_familia_grande_ausente_en_el_challenger_no_permite_promover():
    """En `evaluar_promocion`, si una familia grande del champion no aparece en el challenger su
    costo es NaN y `(nan - c) / c > umbral` es False: la regla por familia la ignora y, sin el
    check de filas completas, el challenger se promueve."""
    champion = ResumenEvaluacion(
        100.0, 0.20, 0.80, 0.9, familias={"A": (500.0, 60.0), "B": (500.0, 40.0)}
    )
    challenger = ResumenEvaluacion(50.0, 0.19, 0.80, 0.9, familias={"B": (500.0, 40.0)})
    assert not evaluar_promocion(challenger, champion, ConfigPromocion()).promover


# ------------------------------- H-REP-1 `reproducir` no usa el modelo_id del manifiesto
@pytest.fixture
def dir_data(almacen_sin_correcciones, tmp_path, monkeypatch):
    monkeypatch.setenv("REPOSICION_GIT_COMMIT", "abc123")
    destino = tmp_path / "data"
    for sub in ("ledger", "limpio"):
        shutil.copytree(almacen_sin_correcciones / sub, destino / sub)
    return destino


def test_reproducir_usa_el_modelo_registrado_en_el_manifiesto(
    dir_data, cfg_fuentes, cfg_validacion
):
    """El docstring de `reproduccion.py` dice que las entradas son "el modelo registrado
    (`modelo_id`)", pero `reproducir` llama a `pronosticar_corte`, que vuelve a resolver
    `champion_vigente(corte)`. Si después de publicar se promueve otro modelo con
    `fecha_promocion <= corte` (p. ej. un reentrenamiento manual con `forzar` ese mismo lunes),
    la publicación —intacta y con su modelo aún en `data/models`— figura como NO reproducida."""
    cfgs = configs(cfg_fuentes, cfg_validacion)
    corte = date(2017, 2, 27)
    metricas = pd.DataFrame(
        [{"nivel": "global", "clave": "", "costo_total": 1.0, "wape": 0.2,
          "cobertura_p10_p90": 0.8, "fill_rate": 0.9}]
    )  # fmt: skip
    modelo = entrenar_modelo("baseline", corte, dir_data, cfgs)
    a = registrar(modelo, "baseline", corte, metricas, dir_data, huella="a")
    anotar_decision(a, Decision(True, ["inicial"]), corte, dir_data)
    destino = pronosticar_corte(corte, dir_data, cfgs)
    assert json.loads((destino / "manifest.json").read_text())["modelo_id"] == a

    b = registrar(modelo, "baseline", corte, metricas, dir_data, huella="b")  # manual, mismo día
    anotar_decision(b, Decision(True, ["reentrenamiento manual"]), corte, dir_data)

    res = reproducir(corte, 1, dir_data, cfgs, commit="abc123")
    assert res.reproducido, res.texto()


# ------------------------------------------- H-MOD-2 día sin operación como lag_1 (1-ene)
def test_dia_sin_operacion_no_se_usa_como_lag_1():
    """`validation.yaml` reconoce días sin operación (`dias_sin_operacion: ["12-25"]`) pero las
    features no los consultan, y el 1-ene (ventas ~1% de lo normal en todos los años) no está en
    la lista. En el corte 2017-01-02 `lag_1` = ventas del 1-ene ≈ 0 y LightGBM recorta TODO el
    horizonte (sesgo -51% en h=1..14; intercambiar solo `lag_1` por el de 01-09 baja el WAPE de
    0.52 a 0.22, ver `diagnostico_corte_2017_01_02.py`). Aquí: con el 1-ene casi en cero,
    `lag_1` del corte 01-02 debería ser NaN o el último día con operación, no ~0."""
    datos = datos_sinteticos()
    v = datos["ventas"]
    datos["ventas"] = v.assign(
        sales=np.where(v["date"] == pd.Timestamp("2017-01-01"), 0.01 * v["sales"], v["sales"])
    )
    X = construir_features(
        datos,
        [date(2017, 1, 2)],
        ConfigModelo(cuantiles_reporte=[0.5], dias_sin_operacion=["01-01", "12-25"]),
        FUENTES,
        False,
    )
    lag1 = X["lag_1"].to_numpy()
    media7 = X["media_7"].to_numpy()
    assert not (lag1 < 0.05 * media7).any(), "lag_1 toma el valor del día sin operación"


def test_lag_1_es_el_del_ultimo_dia_con_operacion_y_las_medias_ignoran_el_dia_cerrado():
    """Con `dias_sin_operacion` el `lag_1` del corte 01-02 es el del 12-31 y el 01-01 no entra en
    las medias móviles; sin la configuración, el comportamiento anterior no cambia."""
    datos = datos_sinteticos()
    v = datos["ventas"]
    datos["ventas"] = v.assign(
        sales=np.where(v["date"] == pd.Timestamp("2017-01-01"), 0.0, v["sales"])
    )
    cfg = ConfigModelo(cuantiles_reporte=[0.5], dias_sin_operacion=["01-01"])
    X = construir_features(datos, [date(2017, 1, 2)], cfg, FUENTES, False)
    X = X[X["h"] == 1].assign(store_nbr=lambda d: d["store_nbr"].astype(int))
    v31 = v[v["date"] == "2016-12-31"].set_index(["store_nbr", "family"])["sales"]
    llaves = list(zip(X["store_nbr"], X["family"].astype(str), strict=True))
    esperado = v31.reindex(llaves)
    assert np.allclose(X["lag_1"].to_numpy(), esperado.to_numpy(), equal_nan=True)
    sin_cfg = construir_features(
        datos, [date(2017, 1, 2)], ConfigModelo(cuantiles_reporte=[0.5]), FUENTES, False
    )
    assert (sin_cfg[sin_cfg["h"] == 1]["lag_1"] == 0).all()
