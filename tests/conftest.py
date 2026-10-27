from pathlib import Path

import pytest

from reposicion.fuentes import ConfigFuentes, cargar_fuentes
from reposicion.simulador import ConfigSimulador, generar
from reposicion.validacion import ConfigValidacion, cargar_validacion
from tests.sinteticos import crear_config, escribir_kaggle

RAIZ = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def kaggle_sintetico(tmp_path_factory) -> Path:
    return escribir_kaggle(tmp_path_factory.mktemp("kaggle") / "kaggle")


@pytest.fixture(scope="session")
def config_sintetica() -> ConfigSimulador:
    return crear_config()


@pytest.fixture(scope="session")
def bandeja_sintetica(kaggle_sintetico, config_sintetica, tmp_path_factory) -> tuple[Path, Path]:
    """(histórico, bandeja) generados por el simulador con los escenarios sintéticos."""
    raiz = tmp_path_factory.mktemp("sintetico")
    generar(kaggle_sintetico, config_sintetica, raiz / "historico", raiz / "bandeja")
    return raiz / "historico", raiz / "bandeja"


@pytest.fixture(scope="session")
def cfg_fuentes() -> ConfigFuentes:
    return cargar_fuentes(RAIZ / "config" / "sources.yaml")


@pytest.fixture(scope="session")
def cfg_validacion() -> ConfigValidacion:
    return cargar_validacion(RAIZ / "config" / "validation.yaml")
