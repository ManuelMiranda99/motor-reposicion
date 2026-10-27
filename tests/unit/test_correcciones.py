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
