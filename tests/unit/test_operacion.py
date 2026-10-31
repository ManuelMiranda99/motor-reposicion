from datetime import date

import pytest

from reposicion.operacion import (
    cargar_operacion,
    es_primer_lunes,
    ultimo_primer_lunes,
)
from tests.conftest import RAIZ

YAML = RAIZ / "config" / "operacion.yaml"


def test_config_por_defecto():
    cfg = cargar_operacion(YAML, env={})
    assert (cfg.inicio, cfg.fin) == (date(2017, 1, 2), date(2017, 8, 14))
    assert cfg.push_remoto == "auto"
    assert cfg.rama_publicaciones == "publicaciones"


def test_variables_de_entorno_sobrescriben_el_periodo():
    env = {"REPOSICION_INICIO": "2017-09-04", "REPOSICION_FIN": "2017-12-25"}
    cfg = cargar_operacion(YAML, env=env)
    assert (cfg.inicio, cfg.fin) == (date(2017, 9, 4), date(2017, 12, 25))


def test_variables_vacias_se_ignoran():
    cfg = cargar_operacion(YAML, env={"REPOSICION_INICIO": "", "REPOSICION_FIN": "  "})
    assert cfg.inicio == date(2017, 1, 2)


def test_periodo_invertido_falla():
    with pytest.raises(ValueError, match="anterior"):
        cargar_operacion(YAML, env={"REPOSICION_INICIO": "2018-01-01"})


@pytest.mark.parametrize(
    ("dia", "esperado"),
    [
        (date(2017, 1, 2), True),  # primer lunes de enero
        (date(2017, 1, 9), False),
        (date(2017, 2, 6), True),
        (date(2017, 3, 6), True),
        (date(2017, 3, 13), False),
        (date(2017, 5, 1), True),  # el día 1 es lunes
        (date(2017, 5, 8), False),
        (date(2017, 3, 7), False),  # martes del 1-7: no es lunes
    ],
)
def test_es_primer_lunes(dia, esperado):
    assert es_primer_lunes(dia) is esperado


@pytest.mark.parametrize(
    ("corte", "esperado"),
    [
        (date(2017, 3, 13), date(2017, 3, 6)),
        (date(2017, 3, 6), date(2017, 3, 6)),
        (date(2017, 1, 2), date(2017, 1, 2)),
        (date(2017, 1, 9), date(2017, 1, 2)),
        (date(2017, 3, 3), date(2017, 2, 6)),  # antes del primer lunes de marzo
        (date(2017, 5, 31), date(2017, 5, 1)),
        (date(2019, 1, 2), date(2018, 12, 3)),  # cruza el año
    ],
)
def test_ultimo_primer_lunes(corte, esperado):
    r = ultimo_primer_lunes(corte)
    assert r == esperado
    assert es_primer_lunes(r) and r <= corte
