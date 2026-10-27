from datetime import date

import pandas as pd
import pyarrow.parquet as pq

from reposicion.almacen import leer_parquet
from reposicion.fuentes import ConfigFuente, fecha_disponible_historica
from reposicion.io import escribir_parquet


def _df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "fecha": pd.to_datetime(["2017-01-01", "2017-01-02"]),
            "n": [1, 2],
            "x": [1.5, None],
            "t": ["a", "b"],
            "b": [True, False],
        }
    )


def test_escribir_parquet_determinista(tmp_path):
    escribir_parquet(_df(), tmp_path / "a.parquet")
    escribir_parquet(_df(), tmp_path / "b.parquet")
    assert (tmp_path / "a.parquet").read_bytes() == (tmp_path / "b.parquet").read_bytes()
    assert not list(tmp_path.glob("*.tmp"))


def test_parquet_tipos_explicitos_y_ida_y_vuelta(tmp_path):
    escribir_parquet(_df(), tmp_path / "a.parquet")
    esquema = pq.read_schema(tmp_path / "a.parquet")
    assert str(esquema.field("fecha").type) == "date32[day]"
    assert str(esquema.field("n").type) == "int64"
    assert esquema.metadata is None or b"pandas" not in esquema.metadata
    leido = leer_parquet(tmp_path / "a.parquet")
    assert leido["fecha"].tolist() == _df()["fecha"].tolist()
    assert pd.isna(leido["x"].iloc[1])


def _cfg(**regla) -> ConfigFuente:
    return ConfigFuente(columnas={"date": "fecha"}, llave=["date"], disponibilidad_historica=regla)


def test_fecha_disponible_historica():
    assert fecha_disponible_historica(_cfg(tipo="dias", dias=1), date(2016, 12, 11)) == date(
        2016, 12, 12
    )
    assert fecha_disponible_historica(_cfg(tipo="dias", dias=-10), date(2016, 12, 12)) == date(
        2016, 12, 2
    )
    # feriados: fecha_dato = inicio del trimestre; llega al inicio del trimestre anterior
    regla = {"tipo": "trimestre_anticipado", "trimestres": 1}
    assert fecha_disponible_historica(_cfg(**regla), date(2017, 7, 1)) == date(2017, 4, 1)
    assert fecha_disponible_historica(_cfg(**regla), date(2017, 1, 1)) == date(2016, 10, 1)
    assert fecha_disponible_historica(_cfg(tipo="siempre"), date(2017, 1, 1)) == date(1900, 1, 1)
