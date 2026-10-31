"""Pruebas de `reproducir`: recalcular una publicación y compararla con su manifiesto.

Bandeja sintética y baseline (sin champion registrado): nunca leen `data/` real.
"""

import json
import shutil
from datetime import date
from pathlib import Path

import pytest

from reposicion.fuentes import cargar_fuentes
from reposicion.parametros import Configs
from reposicion.publicacion import directorio_publicacion
from reposicion.reproduccion import PublicacionNoEncontrada, reproducir
from reposicion.simulador import generar
from reposicion.validacion import cargar_validacion
from tests.integration.test_e2e import CORTES, ciclo, config_e2e
from tests.sinteticos import hashes_dir, preparar_data
from tests.unit.test_backtest import NEGOCIO, cfg_modelo

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module", autouse=True)
def _commit_fijo():
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("REPOSICION_GIT_COMMIT", "repro")
        yield


@pytest.fixture(scope="module")
def corrida(kaggle_sintetico, tmp_path_factory) -> tuple[Path, Configs]:
    from tests.conftest import RAIZ

    raiz = tmp_path_factory.mktemp("repro")
    generar(kaggle_sintetico, config_e2e(), raiz / "historico", raiz / "bandeja")
    cfgs = Configs(
        cfg_modelo(),
        NEGOCIO,
        cargar_fuentes(RAIZ / "config" / "sources.yaml"),
        cargar_validacion(RAIZ / "config" / "validation.yaml"),
    )
    datos = preparar_data(raiz / "data", raiz / "historico")
    for corte in CORTES[:5]:  # 01-02 … 01-30
        ciclo(corte, datos, raiz / "bandeja", cfgs)
    return datos, cfgs


def test_reproduce_rev1(corrida):
    datos, cfgs = corrida
    res = reproducir(date(2017, 1, 16), 1, datos, cfgs, commit="repro")
    assert res.reproducido, res.texto()
    assert res.datos_hasta == date(2017, 1, 16)  # rev=1: el corte
    assert "REPRODUCIDO ✓" in res.texto()


def test_reproduce_una_revision_con_su_datos_hasta(corrida):
    datos, cfgs = corrida
    corte = date(2017, 1, 2)  # tiene rev=2 por la corrección de ventas del 01-05
    manifiesto = json.loads(
        (directorio_publicacion(datos, corte, 2) / "manifest.json").read_text(encoding="utf-8")
    )
    res = reproducir(corte, 2, datos, cfgs, commit="repro")
    assert res.reproducido, res.texto()
    assert res.datos_hasta == date.fromisoformat(manifiesto["datos_hasta"]) > corte


def test_no_toca_lo_publicado(corrida):
    datos, cfgs = corrida
    antes = hashes_dir(datos)
    reproducir(date(2017, 1, 16), 1, datos, cfgs, commit="repro")
    reproducir(date(2017, 1, 2), 2, datos, cfgs, commit="repro")
    assert hashes_dir(datos) == antes


def test_avisa_si_el_commit_difiere(corrida):
    datos, cfgs = corrida
    res = reproducir(date(2017, 1, 16), 1, datos, cfgs, commit="otro-commit")
    assert res.reproducido  # el commit no cambia el resultado: solo se avisa
    assert any("git worktree add ../repro repro" in a for a in res.avisos)


def test_detecta_una_publicacion_alterada(corrida, tmp_path):
    datos, cfgs = corrida
    copia = tmp_path / "data"
    shutil.copytree(datos, copia, symlinks=True)
    ruta = directorio_publicacion(copia, date(2017, 1, 16), 1) / "manifest.json"
    manifiesto = json.loads(ruta.read_text(encoding="utf-8"))
    manifiesto["sha256_archivos"]["pedido.parquet"] = "0" * 64
    ruta.write_text(json.dumps(manifiesto), encoding="utf-8")
    res = reproducir(date(2017, 1, 16), 1, copia, cfgs, commit="repro")
    assert not res.reproducido
    assert any("pedido.parquet" in d for d in res.diferencias)
    assert "NO REPRODUCIDO" in res.texto()


def test_publicacion_inexistente(corrida):
    datos, cfgs = corrida
    with pytest.raises(PublicacionNoEncontrada):
        reproducir(date(2017, 1, 16), 9, datos, cfgs, commit="repro")
