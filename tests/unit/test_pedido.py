import logging

import pandas as pd
import pytest
from pydantic import ValidationError

from reposicion.parametros import ConfigNegocio, cargar_configs, cargar_negocio
from reposicion.pedido import calcular_pedido, cuantil_critico, grupo_de_familia
from tests.conftest import RAIZ

CORTE = pd.Timestamp("2017-03-13")


def negocio(**cambios) -> ConfigNegocio:
    base = {
        "cobertura_dias": 7,
        "lead_time_dias": 0,
        "grupos": {
            "perecederos": {"c_quiebre": 1.0, "c_merma": 1.5, "familias": ["PRODUCE"]},
            "default": {"c_quiebre": 1.0, "c_merma": 0.5},
        },
    }
    base.update(cambios)
    return ConfigNegocio.model_validate(base)


def pronostico(columnas: dict[str, float], familia="PRODUCE") -> pd.DataFrame:
    """14 días con cuantiles constantes por día."""
    dias = pd.date_range(CORTE, periods=14)
    df = pd.DataFrame({"corte": CORTE, "store_nbr": 1, "family": familia, "fecha_objetivo": dias})
    for c, v in columnas.items():
        df[c] = v
    return df


def test_cuantil_critico():
    assert cuantil_critico(1.0, 1.5) == 0.40
    assert cuantil_critico(1.0, 0.1) == 0.91
    assert cuantil_critico(1.0, 0.5) == 0.67
    assert cuantil_critico(1.0, 1.0) == 0.5


def test_grupo_de_familia():
    cfg = negocio()
    assert grupo_de_familia("PRODUCE", cfg) == "perecederos"
    assert grupo_de_familia("BOOKS", cfg) == "default"


def test_pedido_suma_cuantiles_en_la_cobertura():
    p = pronostico({"q0.10": 1.0, "q0.40": 2.0, "q0.50": 3.0, "q0.67": 4.0, "q0.90": 5.0})
    ped = calcular_pedido(p, negocio())
    assert len(ped) == 1
    f = ped.iloc[0]
    assert f["grupo"] == "perecederos" and f["cuantil_critico"] == 0.40
    assert f["demanda_cuantil"] == pytest.approx(7 * 2.0)  # 7 días de cobertura
    assert f["cobertura_desde"] == CORTE and f["cobertura_hasta"] == CORTE + pd.Timedelta(days=6)
    assert f["pedido"] == 14


def test_pedido_redondea_hacia_arriba_y_descuenta_inventario():
    p = pronostico({"q0.40": 1.01})
    assert calcular_pedido(p, negocio()).iloc[0]["pedido"] == 8  # 7.07 → 8
    ped = calcular_pedido(p, negocio(inventario_inicial=5))
    assert ped.iloc[0]["pedido"] == 3  # 7.07 - 5 = 2.07 → 3
    assert calcular_pedido(p, negocio(inventario_inicial=100)).iloc[0]["pedido"] == 0


def test_pedido_cambia_si_cambian_costos(tmp_path):
    """Mismo pronóstico y otro YAML → otro pedido, sin tocar código."""
    p = pronostico({"q0.40": 2.0, "q0.67": 3.0, "q0.91": 5.0}, familia="GROCERY I")
    cfg = cargar_configs(RAIZ / "config")
    original = calcular_pedido(p, cfg.negocio).iloc[0]
    texto = (RAIZ / "config" / "business.yaml").read_text(encoding="utf-8")
    otro = tmp_path / "business.yaml"
    otro.write_text(texto.replace("c_merma: 0.5", "c_merma: 0.1"), encoding="utf-8")  # default
    nuevo = calcular_pedido(p, cargar_negocio(otro)).iloc[0]
    assert (original["cuantil_critico"], original["pedido"]) == (0.67, 21)
    assert (nuevo["cuantil_critico"], nuevo["pedido"]) == (0.91, 35)


def test_pedido_interpola_cuantil_faltante(caplog):
    p = pronostico({"q0.10": 0.0, "q0.50": 2.0, "q0.90": 4.0}, familia="BOOKS")  # τ = 0.67
    with caplog.at_level(logging.WARNING):
        ped = calcular_pedido(p, negocio())
    esperado = 2.0 + (0.67 - 0.5) / 0.4 * 2.0  # 2.85 por día
    assert ped.iloc[0]["demanda_cuantil"] == pytest.approx(7 * esperado)
    assert "interpola" in caplog.text


def test_lead_time_desplaza_la_cobertura():
    p = pronostico({"q0.40": 1.0})
    ped = calcular_pedido(p, negocio(lead_time_dias=2)).iloc[0]
    assert ped["cobertura_desde"] == CORTE + pd.Timedelta(days=2)
    assert ped["cobertura_hasta"] == CORTE + pd.Timedelta(days=8)


def test_config_exige_default_y_familias_unicas():
    with pytest.raises(ValidationError, match="default"):
        ConfigNegocio.model_validate({"grupos": {"a": {"c_quiebre": 1, "c_merma": 1}}})
    with pytest.raises(ValidationError, match="PRODUCE"):
        negocio(
            grupos={
                "a": {"c_quiebre": 1, "c_merma": 1, "familias": ["PRODUCE"]},
                "b": {"c_quiebre": 1, "c_merma": 1, "familias": ["PRODUCE"]},
                "default": {"c_quiebre": 1, "c_merma": 1},
            }
        )


def test_business_yaml_real_es_valido():
    cfg = cargar_configs(RAIZ / "config").negocio
    assert grupo_de_familia("LIQUOR,WINE,BEER", cfg) == "no_perecederos"
    assert grupo_de_familia("GROCERY I", cfg) == "default"
