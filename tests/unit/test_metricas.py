import numpy as np
import pytest

from reposicion.metricas import (
    cobertura,
    costo_newsvendor,
    fill_rate,
    pct_merma,
    pinball,
    rmsle,
    wape,
)


def test_wape():
    assert wape([10, 20], [12, 15]) == pytest.approx((2 + 5) / 30)
    assert np.isnan(wape([0, 0], [1, 1]))


def test_rmsle():
    esperado = np.sqrt(np.mean([(np.log1p(3) - np.log1p(1)) ** 2, 0.0]))
    assert rmsle([1, 5], [3, 5]) == pytest.approx(esperado)
    assert rmsle([1], [-4]) == pytest.approx(np.log1p(1))  # los negativos se recortan a 0


def test_pinball():
    # q=0.9: subpronóstico (y=10, p=6) cuesta 0.9*4; sobrepronóstico (y=2, p=6) cuesta 0.1*4
    assert pinball([10, 2], [6, 6], 0.9) == pytest.approx((3.6 + 0.4) / 2)
    assert pinball([5], [5], 0.5) == 0


def test_cobertura():
    assert cobertura([1, 5, 9, 12], [2, 2, 2, 2], [10, 10, 10, 10]) == pytest.approx(0.5)
    assert cobertura([2, 10], [2, 2], [10, 10]) == 1.0  # los bordes cuentan


def test_newsvendor():
    y, p = [10, 10], [6, 15]  # faltan 4 y sobran 5
    assert costo_newsvendor(y, p, 1.0, 0.5) == pytest.approx(4 * 1.0 + 5 * 0.5)
    assert fill_rate(y, p) == pytest.approx((6 + 10) / 20)
    assert pct_merma(y, p) == pytest.approx(5 / 21)
