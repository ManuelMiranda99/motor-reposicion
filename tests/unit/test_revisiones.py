"""Revisiones por correcciones (bandeja sintética: corrección de ventas 01-05 entregada el 01-09,
ventas tardías del 01-12 entregadas el 01-18)."""

import json
from datetime import date

import pandas as pd
import pytest

from reposicion.almacen import leer_parquet
from reposicion.ingesta import ingestar
from reposicion.parametros import ConfigMonitoreo, Configs
from reposicion.publicacion import directorio_publicacion, pronosticar_corte
from reposicion.revisiones import cortes_publicados, emitir_revisiones
from tests.sinteticos import hashes_dir, preparar_data
from tests.unit.test_backtest import NEGOCIO, cfg_modelo


@pytest.fixture
def cfgs(cfg_fuentes, cfg_validacion) -> Configs:
    return Configs(cfg_modelo(), NEGOCIO, cfg_fuentes, cfg_validacion)


@pytest.fixture
def dir_data(bandeja_sintetica, cfg_fuentes, cfg_validacion, tmp_path, monkeypatch):
    monkeypatch.setenv("REPOSICION_GIT_COMMIT", "abc123")
    datos = preparar_data(tmp_path / "data", bandeja_sintetica[0])
    ingestar(date(2017, 2, 28), datos, bandeja_sintetica[1], cfg_fuentes, cfg_validacion)
    return datos


def manifiesto(dir_data, corte: date, rev: int) -> dict:
    ruta = directorio_publicacion(dir_data, corte, rev) / "manifest.json"
    return json.loads(ruta.read_text())


def revisiones(dir_data, corte: date) -> list[str]:
    return sorted(p.name for p in directorio_publicacion(dir_data, corte, 1).parent.glob("rev=*"))


def test_correccion_emite_revision_y_no_toca_rev1(dir_data, cfgs):
    pronosticar_corte(date(2017, 1, 2), dir_data, cfgs)
    antes = hashes_dir(directorio_publicacion(dir_data, date(2017, 1, 2), 1))
    nuevas = emitir_revisiones(date(2017, 1, 9), dir_data, cfgs)  # llega la corrección del 01-05
    assert [p.name for p in nuevas] == ["rev=2"]
    assert hashes_dir(directorio_publicacion(dir_data, date(2017, 1, 2), 1)) == antes
    m = manifiesto(dir_data, date(2017, 1, 2), 2)
    assert m["revision"] == 2 and m["revision_de"] == 1
    assert m["datos_hasta"] == m["emitido_en"] == "2017-01-09"
    assert "ventas 2017-01-05 (entrega 2017-01-09)" in m["motivo"]
    assert manifiesto(dir_data, date(2017, 1, 2), 1).get("emitido_en") is None
    assert m["huella_entradas"] != manifiesto(dir_data, date(2017, 1, 2), 1)["huella_entradas"]


def test_emitir_revisiones_es_idempotente(dir_data, cfgs):
    pronosticar_corte(date(2017, 1, 2), dir_data, cfgs)
    emitir_revisiones(date(2017, 1, 9), dir_data, cfgs)
    antes = hashes_dir(dir_data / "published")
    assert emitir_revisiones(date(2017, 1, 9), dir_data, cfgs) == []
    assert hashes_dir(dir_data / "published") == antes
    assert revisiones(dir_data, date(2017, 1, 2)) == ["rev=1", "rev=2"]  # no hay rev=3


def test_solo_los_cortes_vigentes_y_afectados_generan_revision(dir_data, cfgs):
    for corte in (date(2017, 1, 9), date(2017, 1, 16)):
        pronosticar_corte(corte, dir_data, cfgs)
    assert cortes_publicados(dir_data) == [date(2017, 1, 9), date(2017, 1, 16)]
    # el 01-18 llegan las ventas tardías del 01-12; el 01-23 se detecta (ventana (01-16, 01-23])
    nuevas = emitir_revisiones(date(2017, 1, 23), dir_data, cfgs)
    assert [p.parent.name for p in nuevas] == ["corte=2017-01-16"]
    assert revisiones(dir_data, date(2017, 1, 9)) == ["rev=1"]  # su horizonte terminó el 01-22
    assert "tardío" in manifiesto(dir_data, date(2017, 1, 16), 2)["motivo"]


def test_la_revision_cambia_el_pronostico_porque_ve_el_dato_tardio(dir_data, cfgs):
    pronosticar_corte(date(2017, 1, 16), dir_data, cfgs)
    emitir_revisiones(date(2017, 1, 23), dir_data, cfgs)
    r1 = leer_parquet(directorio_publicacion(dir_data, date(2017, 1, 16), 1) / "pronostico.parquet")
    r2 = leer_parquet(directorio_publicacion(dir_data, date(2017, 1, 16), 2) / "pronostico.parquet")
    qs = [c for c in r1.columns if c.startswith("q")]
    assert not r1[qs].equals(r2[qs])
    assert r1["fecha_objetivo"].equals(r2["fecha_objetivo"])  # mismo corte y horizonte


def test_sin_correcciones_en_la_ventana_no_hay_revision(dir_data, cfgs):
    pronosticar_corte(date(2017, 1, 16), dir_data, cfgs)
    assert emitir_revisiones(date(2017, 2, 6), dir_data, cfgs) == []


def test_reemitir_si_corrige_false_desactiva_las_revisiones(dir_data, cfgs):
    pronosticar_corte(date(2017, 1, 2), dir_data, cfgs)
    sin = Configs(
        cfgs.modelo, cfgs.negocio, cfgs.fuentes, cfgs.validacion,
        monitoreo=ConfigMonitoreo(reemitir_si_corrige=False),
    )  # fmt: skip
    assert emitir_revisiones(date(2017, 1, 9), dir_data, sin) == []
    assert revisiones(dir_data, date(2017, 1, 2)) == ["rev=1"]


def test_sin_publicaciones_ni_ledger_no_falla(tmp_path, cfgs):
    assert emitir_revisiones(date(2017, 1, 9), tmp_path, cfgs) == []
    assert cortes_publicados(tmp_path) == []


def test_datos_hasta_anterior_al_corte_es_invalido(dir_data, cfgs):
    with pytest.raises(ValueError, match="anterior al corte"):
        pronosticar_corte(date(2017, 1, 16), dir_data, cfgs, 2, datos_hasta=date(2017, 1, 9))


def test_datos_hasta_no_filtra_informacion_posterior_al_corte(dir_data, cfgs):
    """Sin correcciones de por medio, ver datos posteriores al corte no cambia el pronóstico."""
    corte = date(2017, 2, 6)
    pronosticar_corte(corte, dir_data, cfgs)
    pronosticar_corte(corte, dir_data, cfgs, 2, datos_hasta=date(2017, 2, 13))
    q = lambda r: leer_parquet(  # noqa: E731
        directorio_publicacion(dir_data, corte, r) / "pronostico.parquet"
    ).drop(columns="modelo_id")
    pd.testing.assert_frame_equal(q(1), q(2))
    assert manifiesto(dir_data, corte, 2)["datos_hasta"] == "2017-02-13"
