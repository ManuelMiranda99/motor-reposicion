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


@pytest.fixture(scope="session")
def almacen_sin_correcciones(
    kaggle_sintetico, cfg_fuentes, cfg_validacion, tmp_path_factory
) -> Path:
    """`dir_data` con la bandeja sintética ingerida sin escenarios (sin correcciones).

    Con correcciones, las features de entrenamiento (datos revisados) difieren de las de
    inferencia por diseño; sin ellas deben ser idénticas.
    """
    from datetime import date

    from reposicion.ingesta import ingestar

    raiz = tmp_path_factory.mktemp("sin_correcciones")
    config = crear_config(escenarios={})
    generar(kaggle_sintetico, config, raiz / "historico", raiz / "bandeja")
    ingestar(date(2017, 2, 28), raiz, raiz / "bandeja", cfg_fuentes, cfg_validacion)
    return raiz
