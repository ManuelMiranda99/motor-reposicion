"""Funciones que ejecutan las tareas de los DAGs (con la bandeja sintética)."""

import json
import logging
from datetime import date

import pytest

from reposicion import orquestacion as orq
from reposicion.almacen import leer_ledger
from reposicion.ingesta import ingestar
from reposicion.publicacion import directorio_publicacion
from tests.conftest import RAIZ
from tests.sinteticos import hashes_dir, preparar_data


@pytest.fixture
def ingerido(bandeja_sintetica, cfg_fuentes, cfg_validacion, tmp_path):
    datos = preparar_data(tmp_path / "data", bandeja_sintetica[0])
    ingestar(date(2017, 2, 28), datos, bandeja_sintetica[1], cfg_fuentes, cfg_validacion)
    return datos


def test_reportar_calidad_cuenta_por_estado_y_avisa_la_cuarentena(ingerido, caplog):
    # 2017-01-16 se entrega la reentrega válida; 2017-01-15 lo inválido (ventas negativas)
    with caplog.at_level(logging.WARNING):
        res = orq.reportar_calidad(date(2017, 1, 15), ingerido)
    ledger = leer_ledger(ingerido)
    dia = ledger[ledger["fecha_entrega"] == "2017-01-15"]
    assert res["archivos"] == len(dia) > 0
    assert sum(res["por_estado"].values()) == len(dia)
    if res["por_estado"].get("cuarentena"):
        assert "cuarentena:" in caplog.text
    assert res["corte"] == "2017-01-15"


def test_reportar_calidad_cuenta_correcciones(ingerido):
    res = orq.reportar_calidad(date(2017, 1, 9), ingerido)  # entrega de la corrección
    assert res["correcciones"] == 1


def test_reportar_calidad_sin_ledger_no_falla(tmp_path):
    assert orq.reportar_calidad(date(2017, 1, 9), tmp_path) == {
        "corte": "2017-01-09",
        "archivos": 0,
    }


def test_asegurar_ingesta_es_idempotente(bandeja_sintetica, cfg_fuentes, tmp_path):
    datos = preparar_data(tmp_path / "data", bandeja_sintetica[0])
    config = RAIZ / "config"
    # se usa la configuración real de fuentes/validación: las fuentes sintéticas son las mismas
    r1 = orq.asegurar_ingesta(date(2017, 1, 20), datos, bandeja_sintetica[1], config)
    h1 = hashes_dir(datos)
    r2 = orq.asegurar_ingesta(date(2017, 1, 20), datos, bandeja_sintetica[1], config)
    assert r1.nuevos > 0 and r2.nuevos == 0
    assert hashes_dir(datos) == h1


def test_registro_evento_pronostico_incluye_manifiestos(tmp_path):
    corte = date(2017, 3, 13)
    rev = directorio_publicacion(tmp_path, corte, 1)
    rev.mkdir(parents=True)
    (rev / "manifest.json").write_text(json.dumps({"corte": "2017-03-13", "revision": 1}))
    res = orq.registro_evento("pronostico", corte, tmp_path)
    assert res == {"manifiestos": {"rev=1": {"corte": "2017-03-13", "revision": 1}}}


def test_registro_evento_sin_publicacion_ni_modelos(tmp_path):
    corte = date(2017, 3, 13)
    assert orq.registro_evento("pronostico", corte, tmp_path) == {"manifiestos": {}}
    assert orq.registro_evento("modelo", corte, tmp_path) == {"modelos": []}
    assert "fase 7" in orq.registro_evento("seguimiento", corte, tmp_path)["estado"]


def test_evaluar_publicados_es_un_stub_explicito(tmp_path, caplog):
    with caplog.at_level(logging.WARNING):
        res = orq.evaluar_publicados(date(2017, 3, 13), tmp_path)
    assert "fase 7" in res["estado"] and "fase 7" in caplog.text
