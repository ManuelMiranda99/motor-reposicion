from datetime import date

import pandas as pd
import pytest

from reposicion.modelos.baseline import Baseline
from reposicion.parametros import ConfigModelo, ConfigPromocion
from reposicion.registro import (
    Decision,
    ResumenEvaluacion,
    anotar_decision,
    cargar_modelo,
    champion_vigente,
    checks_tecnicos,
    construir_modelo_id,
    decision_registrada,
    evaluar_promocion,
    leer_registro,
    registrar,
)

CFG = ConfigPromocion()


def resumen(costo=100.0, wape=0.20, cobertura=0.80, fam_a=100.0, fam_b=100.0, problemas=()):
    """Dos familias con el mismo volumen real (50% cada una)."""
    return ResumenEvaluacion(
        costo_total=costo,
        wape=wape,
        cobertura_p10_p90=cobertura,
        fill_rate=0.95,
        familias={"A": (1000.0, fam_a), "B": (1000.0, fam_b)},
        problemas_tecnicos=list(problemas),
    )


def test_evaluar_promocion_pasa():
    d = evaluar_promocion(resumen(costo=95.0, fam_a=90.0), resumen(), CFG)
    assert d.promover and all(m.startswith("cumple") for m in d.motivos)


def test_evaluar_promocion_falla_por_costo():
    d = evaluar_promocion(resumen(costo=98.0), resumen(), CFG)  # baja solo 2%
    assert not d.promover and any("NO cumple: el costo total" in m for m in d.motivos)


def test_evaluar_promocion_falla_por_wape():
    d = evaluar_promocion(resumen(costo=90.0, wape=0.205), resumen(), CFG)  # +2.5%
    assert not d.promover and any("NO cumple: el WAPE" in m for m in d.motivos)


@pytest.mark.parametrize("cobertura", [0.65, 0.95])
def test_evaluar_promocion_falla_por_cobertura(cobertura):
    d = evaluar_promocion(resumen(costo=90.0, cobertura=cobertura), resumen(), CFG)
    assert not d.promover and any("NO cumple: cobertura" in m for m in d.motivos)


def test_evaluar_promocion_falla_por_familia_grande():
    d = evaluar_promocion(resumen(costo=90.0, fam_a=115.0, fam_b=60.0), resumen(), CFG)
    assert not d.promover and any(
        "NO cumple: familias" in m and "A (+15.0%)" in m for m in d.motivos
    )


def test_familia_pequena_no_bloquea():
    champ = ResumenEvaluacion(100, 0.2, 0.8, 0.9, {"A": (990.0, 90.0), "B": (10.0, 10.0)})
    chall = ResumenEvaluacion(90, 0.2, 0.8, 0.9, {"A": (990.0, 70.0), "B": (10.0, 20.0)})
    assert evaluar_promocion(chall, champ, CFG).promover  # B pesa 1% del volumen


def test_evaluar_promocion_falla_por_checks_tecnicos():
    d = evaluar_promocion(
        resumen(costo=90.0, problemas=["hay NaN en los cuantiles"]), resumen(), CFG
    )
    assert not d.promover and any("checks técnicos" in m for m in d.motivos)


def test_checks_tecnicos():
    ok = pd.DataFrame(
        {"store_nbr": [1, 1], "family": "A", "origen": 0, "h": [1, 2],
         "q0.10": [1.0, 2.0], "q0.90": [2.0, 3.0]}
    )  # fmt: skip
    assert checks_tecnicos(ok) == []
    malo = ok.assign(**{"q0.10": [5.0, -1.0]})
    assert {"hay cuantiles negativos", "hay cuantiles no monótonos"} <= set(checks_tecnicos(malo))


def metricas_falsas(costo=100.0) -> pd.DataFrame:
    return pd.DataFrame(
        [{"nivel": "global", "clave": "", "costo_total": costo, "wape": 0.2,
          "cobertura_p10_p90": 0.8, "fill_rate": 0.9}]
    )  # fmt: skip


def registrar_baseline(dir_data, corte: date, huella: str, costo=100.0) -> str:
    m = Baseline(ConfigModelo(cuantiles_reporte=[0.5]))
    return registrar(m, "baseline", corte, metricas_falsas(costo), dir_data, huella=huella)


def test_modelo_id_incluye_tipo_corte_y_hash():
    a = construir_modelo_id("lgbm", date(2017, 1, 2), "cfg", "huella")
    assert a.startswith("lgbm-2017-01-02-") and len(a.split("-")[-1]) == 8
    assert a == construir_modelo_id("lgbm", date(2017, 1, 2), "cfg", "huella")
    assert a != construir_modelo_id("lgbm", date(2017, 1, 2), "cfg", "otra huella")


def test_registrar_es_idempotente(tmp_path):
    id1 = registrar_baseline(tmp_path, date(2017, 1, 2), "h")
    anotar_decision(id1, Decision(True, ["inicial"]), date(2017, 1, 2), tmp_path)
    antes = (tmp_path / "models" / "registro.parquet").read_bytes()
    id2 = registrar_baseline(tmp_path, date(2017, 1, 2), "h")  # no cambia la promoción
    assert id1 == id2
    assert (tmp_path / "models" / "registro.parquet").read_bytes() == antes
    assert len(leer_registro(tmp_path)) == 1
    assert (tmp_path / "models" / id1 / "metricas_backtest.parquet").exists()
    assert isinstance(cargar_modelo(id1, tmp_path), Baseline)
    assert decision_registrada(id1, tmp_path) == Decision(True, ["inicial"])


def test_champion_vigente_respeta_fecha(tmp_path):
    assert champion_vigente(date(2017, 1, 2), tmp_path) is None
    a = registrar_baseline(tmp_path, date(2017, 1, 2), "a")
    anotar_decision(a, Decision(True, ["inicial"]), date(2017, 1, 2), tmp_path)
    b = registrar_baseline(tmp_path, date(2017, 2, 6), "b")
    anotar_decision(b, Decision(True, ["mejor"]), date(2017, 2, 6), tmp_path)
    c = registrar_baseline(tmp_path, date(2017, 3, 6), "c")
    anotar_decision(c, Decision(False, ["peor"]), date(2017, 3, 6), tmp_path)
    assert champion_vigente(date(2016, 12, 31), tmp_path) is None  # antes de todo
    assert champion_vigente(date(2017, 1, 2), tmp_path) == a
    assert champion_vigente(date(2017, 2, 5), tmp_path) == a  # backfill: aún no existía b
    assert champion_vigente(date(2017, 2, 6), tmp_path) == b
    assert champion_vigente(date(2017, 9, 1), tmp_path) == b  # c no fue promovido


def test_champion_con_misma_fecha_gana_el_promovido_despues(tmp_path):
    a = registrar_baseline(tmp_path, date(2017, 1, 2), "a")
    anotar_decision(a, Decision(True, ["inicial"]), date(2017, 1, 2), tmp_path)
    b = registrar_baseline(tmp_path, date(2017, 1, 2), "b")
    anotar_decision(b, Decision(True, ["challenger"]), date(2017, 1, 2), tmp_path)
    assert champion_vigente(date(2017, 1, 2), tmp_path) == b


def test_cargar_modelo_inexistente(tmp_path):
    with pytest.raises(FileNotFoundError):
        cargar_modelo("lgbm-2017-01-02-deadbeef", tmp_path)


def test_familia_grande_ausente_en_el_challenger_bloquea_la_promocion():
    from reposicion.registro import ResumenEvaluacion, evaluar_promocion

    champ = ResumenEvaluacion(100.0, 0.2, 0.8, 0.9, familias={"A": (900.0, 60.0), "B": (50.0, 4.0)})
    chall = ResumenEvaluacion(50.0, 0.19, 0.8, 0.9, familias={"B": (50.0, 4.0)})
    d = evaluar_promocion(chall, champ, ConfigPromocion())
    assert not d.promover and any("ausente en el challenger" in m for m in d.motivos)
