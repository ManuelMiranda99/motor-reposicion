from datetime import date

import pandas as pd
import pytest

from reposicion.validacion import validar_archivo

D = date(2017, 1, 10)
TIENDAS = {1, 2}
FAMILIAS = {"A", "B"}


def _ventas(**cambios) -> pd.DataFrame:
    filas = [(s, f) for s in sorted(TIENDAS) for f in sorted(FAMILIAS)]
    df = pd.DataFrame(
        {
            "date": [D.isoformat()] * 4,
            "store_nbr": [str(s) for s, _ in filas],
            "family": [f for _, f in filas],
            "sales": ["5.0", "6", "7.5", "8"],
        }
    )
    for col, valores in cambios.items():
        df[col] = valores
    return df


def _validar(texto, fuente="ventas", fecha=D, tiendas=TIENDAS, **kw):
    return validar_archivo(texto, fuente, fecha, kw.pop("cfg"), tiendas, FAMILIAS, **kw)


@pytest.fixture
def v(cfg_fuentes):
    return lambda texto, **kw: _validar(texto, cfg=cfg_fuentes, **kw)


def test_archivo_valido_devuelve_datos_tipados(v):
    r = v(_ventas())
    assert r.valido and not r.errores and not r.advertencias
    assert str(r.datos["date"].dtype).startswith("datetime64")
    assert r.datos["store_nbr"].dtype == "int64" and r.datos["sales"].dtype == "float64"


def test_archivo_vacio_es_error(v):
    assert "vacío" in v(_ventas().iloc[0:0]).errores[0]


def test_columna_faltante_es_error(v):
    r = v(_ventas().drop(columns="sales"))
    assert not r.valido and "ausentes" in r.errores[0] and r.datos is None


def test_columna_extra_es_advertencia_y_se_descarta(v):
    r = v(_ventas().assign(nueva="x"))
    assert r.valido and "extra" in r.advertencias[0] and "nueva" not in r.datos.columns


@pytest.mark.parametrize("malo", ["N/A", "", "abc", "nan", "inf"])
def test_valor_no_convertible_es_error(v, malo):
    r = v(_ventas(sales=["5", malo, "1", "2"]))
    assert not r.valido and "no convertibles" in r.errores[0]


def test_entero_con_decimales_es_error(v):
    r = v(_ventas(store_nbr=["1", "1", "2.5", "2"]))
    assert not r.valido and "store_nbr" in r.errores[0]


def test_fecha_distinta_de_fecha_dato_es_error(v):
    r = v(_ventas(date=[D.isoformat()] * 3 + ["2017-01-11"]))
    assert not r.valido and "fuera de" in r.errores[0]


def test_llave_duplicada_es_error(v):
    r = v(_ventas(family=["A", "A", "B", "B"], store_nbr=["1", "1", "2", "2"]))
    assert not r.valido and "duplicada" in r.errores[0]


def test_negativos_es_error(v):
    r = v(_ventas(sales=["5", "-1", "1", "2"]))
    assert not r.valido and "negativos" in r.errores[0]


def test_tienda_fuera_del_maestro_es_error(v):
    r = v(_ventas(), tiendas={1})
    assert not r.valido and "store_nbr desconocido" in r.errores[0]


def test_familia_desconocida_es_error(v):
    r = v(_ventas(family=["A", "B", "A", "Z"]))
    assert not r.valido and "family desconocida" in r.errores[0]


def test_tienda_en_cero_es_advertencia_no_error(v):
    r = v(_ventas(sales=["0", "0", "7", "8"]))
    assert r.valido and "ventas totales en 0" in r.advertencias[0]


def test_ventas_incompletas_es_advertencia(v):
    r = v(_ventas().iloc[:3])
    assert r.valido and "incompletas" in r.advertencias[0]


def test_completitud_minima_opcional_manda_a_cuarentena(v):
    assert not v(_ventas().iloc[:3], completitud_min=0.9).valido
    assert v(_ventas().iloc[:3], completitud_min=0.5).valido


def test_petroleo_vacio_es_advertencia(v):
    texto = pd.DataFrame({"date": [D.isoformat()], "dcoilwtico": [""]})
    r = v(texto, fuente="petroleo")
    assert r.valido and "petróleo" in r.advertencias[0] and r.datos["dcoilwtico"].isna().all()


def test_feriados_deben_caer_en_el_trimestre(v):
    fila = {"type": "Holiday", "locale": "National", "locale_name": "E", "description": "x"}
    ok = pd.DataFrame([{"date": "2017-07-03", **fila, "transferred": "False"}])
    mal = pd.DataFrame([{"date": "2017-10-03", **fila, "transferred": "False"}])
    assert v(ok, fuente="feriados", fecha=date(2017, 7, 1)).valido
    assert not v(mal, fuente="feriados", fecha=date(2017, 7, 1)).valido


def test_tiendas_no_exige_fecha_ni_maestro(v):
    texto = pd.DataFrame(
        {"store_nbr": ["1"], "city": ["Q"], "state": ["P"], "type": ["A"], "cluster": ["3"]}
    )
    assert v(texto, fuente="tiendas", tiendas=set()).valido
