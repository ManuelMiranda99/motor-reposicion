from datetime import date

import pandas as pd

from reposicion.correcciones import correcciones_entre, cortes_afectados


def _ledger() -> pd.DataFrame:
    filas = [
        ("ventas", "2017-02-03", "2017-02-04", False, False),
        ("ventas", "2017-02-03", "2017-02-10", True, False),
        ("ventas", "2017-03-09", "2017-03-15", False, True),
        ("petroleo", "2017-05-02", "2017-05-09", True, False),
    ]
    return pd.DataFrame(
        {
            "fuente": [f[0] for f in filas],
            "fecha_dato": pd.to_datetime([f[1] for f in filas]),
            "fecha_entrega": pd.to_datetime([f[2] for f in filas]),
            "es_correccion": [f[3] for f in filas],
            "es_tardio": [f[4] for f in filas],
        }
    )


def test_correcciones_entre_usa_intervalo_abierto_por_la_izquierda():
    c = correcciones_entre(_ledger(), date(2017, 2, 10), date(2017, 3, 15))
    assert list(c["fecha_dato"].dt.date) == [date(2017, 3, 9)]  # la del 02-10 queda fuera
    c = correcciones_entre(_ledger(), date(2017, 2, 9), date(2017, 5, 9))
    assert len(c) == 3


def test_cortes_afectados():
    corr = correcciones_entre(_ledger(), date(2017, 2, 9), date(2017, 2, 10))
    cortes = [
        date(2017, 1, 16),
        date(2017, 1, 23),
        date(2017, 1, 30),
        date(2017, 2, 6),
        date(2017, 2, 13),
    ]
    # dato del 02-03; ventana de features 28 días y horizonte 14: P-28 <= 02-03 <= P+13
    # P=01-23 (+13 = 02-05 ok), 01-30, 02-06 se calcularon antes de la entrega (02-10);
    # P=01-16 aún no ve el 02-03 en su horizonte (01-29); 02-13 ya vio la corrección.
    assert cortes_afectados(corr, cortes, 14, 28) == [
        date(2017, 1, 23),
        date(2017, 1, 30),
        date(2017, 2, 6),
    ]


def test_cortes_afectados_vacio():
    assert cortes_afectados(_ledger().iloc[0:0], [date(2017, 1, 2)], 14, 28) == []


def test_llegada_fuera_de_plazo_solo_afecta_a_los_cortes_que_la_habrian_usado():
    """Un tardío (primera versión válida fuera de plazo) con el lag de su fuente afecta a los
    cortes con `fecha_dato + lag <= P < entrega`, no a los que solo la tienen en su horizonte."""
    tardio = pd.DataFrame(
        {
            "fuente": ["ventas"],
            "fecha_dato": pd.to_datetime(["2017-01-29"]),
            "fecha_entrega": pd.to_datetime(["2017-01-31"]),
            "es_correccion": [False],
            "es_tardio": [True],
        }
    )
    cortes = [date(2017, 1, 23), date(2017, 1, 30)]
    # regla conservadora (sin lags): ambos cortes tienen el 01-29 en su horizonte
    assert cortes_afectados(tardio, cortes, 14, 364) == cortes
    # con el lag de ventas (1 día): solo el 01-30 pudo haber usado el dato del 01-29
    assert cortes_afectados(tardio, cortes, 14, 364, {"ventas": 1}) == [date(2017, 1, 30)]
    # una corrección conserva la regla conservadora
    corr = tardio.assign(es_correccion=True, es_tardio=False)
    assert cortes_afectados(corr, cortes, 14, 364, {"ventas": 1}) == cortes
