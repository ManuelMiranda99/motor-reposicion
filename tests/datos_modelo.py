"""Datos en memoria con la forma que devuelve `cargar_datos_asof`, para probar features."""

from __future__ import annotations

import pandas as pd

INICIO = pd.Timestamp("2016-01-01")
FIN = pd.Timestamp("2017-03-31")
TIENDAS = {1: ("Quito", "Pichincha"), 2: ("Cuenca", "Azuay")}
FAMILIAS = ["PRODUCE", "AUTOMOTIVE"]


def numero_dia(fecha) -> int:
    """Número de día desde 2016-01-01 (el 2016-01-01 es 1): es el valor de `sales`."""
    return (pd.Timestamp(fecha) - INICIO).days + 1


def datos_sinteticos() -> dict[str, pd.DataFrame]:
    fechas = pd.date_range(INICIO, FIN)
    base = pd.DataFrame(
        [(f, s, fam) for f in fechas for s in TIENDAS for fam in FAMILIAS],
        columns=["date", "store_nbr", "family"],
    )
    ventas = base.assign(sales=(base["date"] - INICIO).dt.days.astype(float) + 1)
    promociones = base.assign(onpromotion=(base["date"] - INICIO).dt.days % 3)
    transacciones = pd.DataFrame(
        [(f, s) for f in fechas for s in TIENDAS], columns=["date", "store_nbr"]
    )
    transacciones["transactions"] = 1000 + (transacciones["date"] - INICIO).dt.days
    habiles = fechas[fechas.day_of_week < 5]
    petroleo = pd.DataFrame({"date": habiles, "dcoilwtico": 50 + 0.1 * (habiles - INICIO).days})
    feriados = pd.DataFrame(
        [
            ("2017-03-10", "Holiday", "National", "Ecuador", "Nacional", False),
            ("2017-03-14", "Holiday", "Local", "Cuenca", "Local de Cuenca", False),
            ("2017-03-20", "Holiday", "National", "Ecuador", "Transferido", True),
            ("2017-03-22", "Transfer", "National", "Ecuador", "Traslado", False),
            ("2017-03-24", "Bridge", "National", "Ecuador", "Puente", False),
            ("2017-03-25", "Event", "National", "Ecuador", "Evento", False),
        ],
        columns=["date", "type", "locale", "locale_name", "description", "transferred"],
    )
    feriados["date"] = pd.to_datetime(feriados["date"])
    tiendas = pd.DataFrame(
        [(s, c, e, "A", s) for s, (c, e) in TIENDAS.items()],
        columns=["store_nbr", "city", "state", "type", "cluster"],
    )
    return {
        "ventas": ventas,
        "promociones": promociones,
        "transacciones": transacciones,
        "petroleo": petroleo,
        "feriados": feriados,
        "tiendas": tiendas,
    }
