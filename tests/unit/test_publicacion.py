import json
import shutil
from datetime import date

import pandas as pd
import pytest

from reposicion.almacen import leer_ledger, leer_parquet, ruta_ledger, ruta_limpio
from reposicion.entrenamiento import entrenar_modelo, entrenar_y_evaluar
from reposicion.io import escribir_parquet
from reposicion.parametros import ConfigModelo, ConfigNegocio, Configs
from reposicion.publicacion import (
    DatosInsuficientes,
    PublicacionInmutable,
    directorio_publicacion,
    pronosticar_corte,
)
from reposicion.registro import (
    Decision,
    anotar_decision,
    champion_vigente,
    leer_registro,
    registrar,
)
from tests.unit.test_backtest import NEGOCIO

CORTE = date(2017, 2, 27)  # lunes; las ventas llegan hasta el 2017-02-26


def cfg_modelo(**cambios) -> ConfigModelo:
    base = {
        "cuantiles_reporte": [0.1, 0.5, 0.9],
        "ventana_origenes_semanas": 3,
        "backtest": {"n_origenes": 2},
        "lightgbm": {
            "num_boost_round": 8,
            "num_leaves": 7,
            "min_data_in_leaf": 5,
            "num_threads": 2,
        },
        "lightgbm_semanal": {"num_boost_round": 8, "num_leaves": 7, "min_data_in_leaf": 5},
    }
    base.update(cambios)
    return ConfigModelo.model_validate(base)


@pytest.fixture
def cfgs(cfg_fuentes, cfg_validacion) -> Configs:
    return Configs(cfg_modelo(), NEGOCIO, cfg_fuentes, cfg_validacion)


@pytest.fixture
def dir_data(almacen_sin_correcciones, tmp_path, monkeypatch):
    """Copia del almacén sintético (las pruebas escriben en `published/` y `models/`)."""
    monkeypatch.setenv("REPOSICION_GIT_COMMIT", "abc123")
    destino = tmp_path / "data"
    for sub in ("ledger", "limpio"):
        shutil.copytree(almacen_sin_correcciones / sub, destino / sub)
    return destino


def bytes_de(directorio):
    return {p.name: p.read_bytes() for p in sorted(directorio.iterdir())}


def test_pronosticar_corte_idempotente(dir_data, cfgs):
    destino = pronosticar_corte(CORTE, dir_data, cfgs)
    assert destino == directorio_publicacion(dir_data, CORTE, 1)
    primero = bytes_de(destino)
    assert set(primero) == {"pronostico.parquet", "pedido.parquet", "manifest.json"}
    segundo = bytes_de(pronosticar_corte(CORTE, dir_data, cfgs))
    assert primero == segundo
    assert not list(destino.parent.glob("*.tmp"))
    m = json.loads(primero["manifest.json"])
    assert m["git_commit"] == "abc123" and m["calidad"] in {"ok", "degradada"}
    assert any("sin champion" in a for a in m["advertencias"])
    assert set(m["sha256_archivos"]) == {"pronostico.parquet", "pedido.parquet"}
    assert not {"timestamp", "creado_en", "fecha_ejecucion"} & set(m)  # sin reloj


def test_pronostico_tiene_forma_y_valores_validos(dir_data, cfgs):
    destino = pronosticar_corte(CORTE, dir_data, cfgs)
    p = leer_parquet(destino / "pronostico.parquet")
    series = p[["store_nbr", "family"]].drop_duplicates()
    assert len(p) == len(series) * 14 and sorted(p["h"].unique()) == list(range(1, 15))
    assert p["fecha_objetivo"].min() == pd.Timestamp(CORTE)
    assert p["fecha_objetivo"].max() == pd.Timestamp(CORTE) + pd.Timedelta(days=13)
    qs = [c for c in p.columns if c.startswith("q")]
    assert {"q0.10", "q0.50", "q0.67", "q0.90"} <= set(qs)
    assert (p[qs] >= 0).all().all() and not p[qs].isna().any().any()
    assert (p["q0.10"] <= p["q0.90"]).all()
    ped = leer_parquet(destino / "pedido.parquet")
    assert len(ped) == len(series) and (ped["pedido"] >= 0).all()


def test_publicado_inmutable(dir_data, cfgs):
    destino = pronosticar_corte(CORTE, dir_data, cfgs)
    antes = bytes_de(destino)
    ledger = leer_ledger(dir_data)
    ledger.loc[0, "sha256"] = "0" * 64  # otra huella de entradas (p. ej. un archivo corregido)
    escribir_parquet(ledger, ruta_ledger(dir_data))
    with pytest.raises(PublicacionInmutable, match="huella_entradas"):
        pronosticar_corte(CORTE, dir_data, cfgs)
    assert bytes_de(destino) == antes
    # una revisión nueva sí es posible
    assert pronosticar_corte(CORTE, dir_data, cfgs, revision=2).name == "rev=2"


def test_publicado_inmutable_si_cambia_la_configuracion(
    dir_data, cfgs, cfg_fuentes, cfg_validacion
):
    pronosticar_corte(CORTE, dir_data, cfgs)
    otro = Configs(cfgs.modelo, ConfigNegocio.model_validate(
        {"cobertura_dias": 5, "grupos": {"default": {"c_quiebre": 1.0, "c_merma": 0.5}}}
    ), cfg_fuentes, cfg_validacion)  # fmt: skip
    with pytest.raises(PublicacionInmutable, match="sha256_business"):
        pronosticar_corte(CORTE, dir_data, otro)


def test_pronosticar_falla_sin_datos(dir_data, cfgs):
    with pytest.raises(DatosInsuficientes, match="ventas disponibles"):
        pronosticar_corte(date(2017, 3, 20), dir_data, cfgs)  # las ventas llegan hasta el 02-27
    assert not (dir_data / "published").exists()


def test_pronosticar_degradado_con_hueco_menor(dir_data, cfgs):
    ruta = ruta_limpio(dir_data, "ventas")
    ventas = leer_parquet(ruta)
    escribir_parquet(ventas[ventas["fecha_dato"] != pd.Timestamp("2017-02-20")], ruta)
    destino = pronosticar_corte(CORTE, dir_data, cfgs)  # continúa, sin fallar
    m = json.loads((destino / "manifest.json").read_text())
    assert m["calidad"] == "degradada"
    assert any("2017-02-20" in a for a in m["advertencias"])
    assert (destino / "pronostico.parquet").exists()


def test_pedido_en_publicacion_usa_business_yaml(dir_data, cfg_fuentes, cfg_validacion):
    negocio = ConfigNegocio.model_validate(
        {"cobertura_dias": 3, "grupos": {"default": {"c_quiebre": 1.0, "c_merma": 1.0}}}
    )
    destino = pronosticar_corte(
        CORTE, dir_data, Configs(cfg_modelo(), negocio, cfg_fuentes, cfg_validacion)
    )
    ped = leer_parquet(destino / "pedido.parquet")
    assert (ped["cuantil_critico"] == 0.5).all()
    assert (ped["cobertura_hasta"] == pd.Timestamp(CORTE) + pd.Timedelta(days=2)).all()


def test_usa_el_champion_vigente(dir_data, cfgs):
    modelo = entrenar_modelo("baseline", CORTE, dir_data, cfgs)
    metricas = pd.DataFrame(
        [{"nivel": "global", "clave": "", "costo_total": 1.0, "wape": 0.2,
          "cobertura_p10_p90": 0.8, "fill_rate": 0.9}]
    )  # fmt: skip
    mid = registrar(modelo, "baseline", CORTE, metricas, dir_data, huella="x")
    anotar_decision(mid, Decision(True, ["inicial"]), CORTE, dir_data)
    # antes de su fecha de promoción, un backfill no lo ve
    assert champion_vigente(date(2017, 2, 20), dir_data) is None
    destino = pronosticar_corte(CORTE, dir_data, cfgs)
    m = json.loads((destino / "manifest.json").read_text())
    assert m["modelo_id"] == mid
    assert not any("sin champion" in a for a in m["advertencias"])
    assert leer_parquet(destino / "pronostico.parquet")["modelo_id"].eq(mid).all()


def test_entrenar_y_evaluar_registra_y_es_idempotente(dir_data, cfgs):
    corte = date(2017, 2, 28)
    d = entrenar_y_evaluar(corte, dir_data, cfgs)
    reg = leer_registro(dir_data)
    assert set(reg["tipo"]) == {"baseline", "lgbm"}
    base = reg[reg["tipo"] == "baseline"].iloc[0]
    assert base["promovido"] and "champion inicial" in base["motivos"]
    assert base["fecha_promocion"] <= pd.Timestamp(corte)
    assert champion_vigente(corte, dir_data) is not None
    antes = (dir_data / "models" / "registro.parquet").read_bytes()
    assert entrenar_y_evaluar(corte, dir_data, cfgs) == d  # reutiliza la decisión
    assert (dir_data / "models" / "registro.parquet").read_bytes() == antes
