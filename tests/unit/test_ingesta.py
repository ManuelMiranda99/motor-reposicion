import shutil
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

from reposicion.almacen import leer_ledger
from reposicion.asof import asof, fechas_faltantes, ultima_fecha_disponible
from reposicion.ingesta import escanear_bandeja, ingestar
from tests.sinteticos import hashes_dir, preparar_data

FIN = date(2017, 2, 28)


@pytest.fixture
def datos(bandeja_sintetica, tmp_path) -> Path:
    return preparar_data(tmp_path / "data", bandeja_sintetica[0])


@pytest.fixture(scope="module")
def ingerido(bandeja_sintetica, cfg_fuentes, cfg_validacion, tmp_path_factory) -> Path:
    """dir_data con toda la bandeja sintética ingerida (solo lectura: se comparte)."""
    datos = preparar_data(tmp_path_factory.mktemp("ingerido"), bandeja_sintetica[0])
    ingestar(FIN, datos, bandeja_sintetica[1], cfg_fuentes, cfg_validacion)
    return datos


def _fila(ledger, fuente, fecha_dato, **filtro):
    m = (ledger["fuente"] == fuente) & (ledger["fecha_dato"] == pd.Timestamp(fecha_dato))
    for k, val in filtro.items():
        m &= ledger[k] == val
    return ledger[m].sort_values("fecha_entrega")


# ------------------------------------------------------------------------------ escaneo


def test_escanear_respeta_hasta(bandeja_sintetica, cfg_fuentes):
    corte = date(2017, 1, 15)
    archivos = escanear_bandeja(bandeja_sintetica[1], corte, cfg_fuentes)
    assert archivos and all(a.fecha_entrega <= corte for a in archivos)
    assert max(a.fecha_entrega for a in archivos) == corte


def test_escanear_ignora_prefijo_y_nombres_raros(tmp_path, cfg_fuentes, caplog):
    (tmp_path / "2017-01-02").mkdir()
    (tmp_path / "2017-01-02" / "ventas_2017-01-01.csv").write_text("a\n1\n")
    (tmp_path / "2017-01-02" / "_nota.csv").write_text("x")
    (tmp_path / "2017-01-02" / "raro.txt").write_text("x")
    (tmp_path / "2017-01-02" / "desconocida_2017-01-01.csv").write_text("x")
    (tmp_path / "_escenarios.csv").write_text("x")
    (tmp_path / "carpeta_rara").mkdir()
    with caplog.at_level("WARNING"):
        archivos = escanear_bandeja(tmp_path, date(2017, 12, 31), cfg_fuentes)
    assert [a.relativa for a in archivos] == ["2017-01-02/ventas_2017-01-01.csv"]
    assert "raro.txt" in caplog.text and "carpeta_rara" in caplog.text


def test_escanear_pone_tiendas_primero(bandeja_sintetica, cfg_fuentes):
    archivos = escanear_bandeja(bandeja_sintetica[1], date(2017, 1, 20), cfg_fuentes)
    del_dia = [a.fuente for a in archivos if a.fecha_entrega == date(2017, 1, 20)]
    assert del_dia[0] == "tiendas"


# ------------------------------------------------------------------------------ ingesta


def test_ingesta_no_modifica_bandeja(datos, bandeja_sintetica, cfg_fuentes, cfg_validacion):
    antes = hashes_dir(bandeja_sintetica[1])
    ingestar(FIN, datos, bandeja_sintetica[1], cfg_fuentes, cfg_validacion)
    ingestar(FIN, datos, bandeja_sintetica[1], cfg_fuentes, cfg_validacion)
    assert hashes_dir(bandeja_sintetica[1]) == antes
    # y la copia en raw es byte a byte
    assert (datos / "raw").is_dir()
    for ruta, h in hashes_dir(datos / "raw").items():
        assert antes[ruta] == h


def test_ingesta_idempotente(datos, bandeja_sintetica, cfg_fuentes, cfg_validacion):
    r1 = ingestar(FIN, datos, bandeja_sintetica[1], cfg_fuentes, cfg_validacion)
    despues_de_una = hashes_dir(datos)
    r2 = ingestar(FIN, datos, bandeja_sintetica[1], cfg_fuentes, cfg_validacion)
    assert r1.nuevos > 0 and r2.nuevos == 0
    assert hashes_dir(datos) == despues_de_una


def test_ingesta_incremental_igual_a_completa(
    datos, bandeja_sintetica, cfg_fuentes, cfg_validacion, tmp_path
):
    completa = preparar_data(tmp_path / "completa", bandeja_sintetica[0])
    ingestar(FIN, completa, bandeja_sintetica[1], cfg_fuentes, cfg_validacion)
    dia = date(2017, 1, 2)
    while dia <= FIN:
        ingestar(dia, datos, bandeja_sintetica[1], cfg_fuentes, cfg_validacion)
        dia += timedelta(days=1)
    assert hashes_dir(datos / "ledger") == hashes_dir(completa / "ledger")
    assert hashes_dir(datos / "limpio") == hashes_dir(completa / "limpio")
    assert hashes_dir(datos / "raw") == hashes_dir(completa / "raw")


def test_ledger_estados_de_los_escenarios(ingerido):
    ledger = leer_ledger(ingerido)
    assert set(ledger["estado"]) == {"valido", "cuarentena", "duplicado"}
    cuarentena = ledger[ledger["estado"] == "cuarentena"]
    assert set(zip(cuarentena["fuente"], cuarentena["fecha_dato"].dt.date, strict=True)) == {
        ("ventas", date(2017, 1, 14)),
        ("transacciones", date(2017, 1, 20)),
        ("ventas", date(2017, 1, 22)),
        ("promociones", date(2017, 2, 20)),
        ("ventas", date(2017, 1, 24)),
    }
    assert (cuarentena["version"] == 0).all() and (cuarentena["errores"] != "").all()
    assert not ledger.duplicated(["archivo", "sha256"]).any()


def test_duplicado_identico_no_crea_version(ingerido):
    f = _fila(leer_ledger(ingerido), "ventas", "2017-01-06")
    assert list(f["estado"]) == ["valido", "duplicado"]
    assert list(f["version"]) == [1, 1] and not f["es_correccion"].any()


def test_correccion_crea_version_2_y_asof_la_ve_solo_despues(ingerido):
    f = _fila(leer_ledger(ingerido), "ventas", "2017-01-05")
    assert list(f["version"]) == [1, 2] and list(f["es_correccion"]) == [False, True]
    antes = asof("ventas", date(2017, 1, 8), ingerido)
    despues = asof("ventas", date(2017, 1, 9), ingerido)
    dia = pd.Timestamp("2017-01-05")
    v1, v2 = antes[antes["fecha_dato"] == dia], despues[despues["fecha_dato"] == dia]
    assert len(v1) == len(v2) == 4  # 2 tiendas × 2 familias (la 3 aún no existe)
    assert v2["sales"].sum() > v1["sales"].sum()


def test_reentrega_valida_tras_cuarentena_es_version_1(ingerido):
    f = _fila(leer_ledger(ingerido), "ventas", "2017-01-14")
    assert list(f["estado"]) == ["cuarentena", "valido"]
    assert list(f["version"]) == [0, 1] and not f["es_correccion"].any()
    assert (asof("ventas", date(2017, 1, 16), ingerido)["sales"] >= 0).all()


def test_duplicado_de_version_vieja_es_version_nueva(
    datos, bandeja_sintetica, cfg_fuentes, cfg_validacion, tmp_path
):
    bandeja = tmp_path / "bandeja"
    shutil.copytree(bandeja_sintetica[1], bandeja)
    # la fuente vuelve a enviar el contenido de la v1 (2017-01-06) como vigente
    (bandeja / "2017-01-12").mkdir(exist_ok=True)
    shutil.copyfile(
        bandeja / "2017-01-06" / "ventas_2017-01-05.csv",
        bandeja / "2017-01-12" / "ventas_2017-01-05.csv",
    )
    ingestar(FIN, datos, bandeja, cfg_fuentes, cfg_validacion)
    f = _fila(leer_ledger(datos), "ventas", "2017-01-05")
    assert list(f["version"]) == [1, 2, 3] and list(f["es_correccion"]) == [False, True, True]


def test_archivo_modificado_en_la_bandeja_se_ignora(
    datos, bandeja_sintetica, cfg_fuentes, cfg_validacion, tmp_path, caplog
):
    bandeja = tmp_path / "bandeja"
    shutil.copytree(bandeja_sintetica[1], bandeja)
    ingestar(FIN, datos, bandeja, cfg_fuentes, cfg_validacion)
    antes = hashes_dir(datos)
    with open(bandeja / "2017-01-03" / "ventas_2017-01-02.csv", "a") as f:
        f.write("2017-01-02,1,A,1\n")
    resumen = ingestar(FIN, datos, bandeja, cfg_fuentes, cfg_validacion)
    assert resumen.conflictos == 1 and resumen.nuevos == 0
    assert hashes_dir(datos) == antes


def test_tienda_nueva_valida_solo_desde_su_alta(ingerido):
    ledger = leer_ledger(ingerido)
    assert set(asof("tiendas", date(2017, 1, 19), ingerido)["store_nbr"]) == {1, 2}
    assert set(asof("tiendas", date(2017, 1, 20), ingerido)["store_nbr"]) == {1, 2, 3}
    desconocidas = ledger[ledger["errores"].str.contains("desconocido")]
    assert list(desconocidas["fuente"]) == ["promociones"]  # solo el escenario con tienda 999
    ventas = asof("ventas", FIN, ingerido)
    assert ventas[ventas["store_nbr"] == 3]["fecha_dato"].min() >= pd.Timestamp("2017-01-20")


def test_tardio_marcado_y_no_visible_antes_de_su_entrega(ingerido):
    f = _fila(leer_ledger(ingerido), "ventas", "2017-01-12")
    assert list(f["es_tardio"]) == [True] and f["fecha_entrega"].iloc[0] == pd.Timestamp(
        "2017-01-18"
    )
    assert pd.Timestamp("2017-01-12") not in set(
        asof("ventas", date(2017, 1, 17), ingerido)["fecha_dato"]
    )
    assert pd.Timestamp("2017-01-12") in set(
        asof("ventas", date(2017, 1, 18), ingerido)["fecha_dato"]
    )
    assert date(2017, 1, 12) in fechas_faltantes("ventas", date(2017, 1, 17), 28, ingerido)
    assert date(2017, 1, 12) not in fechas_faltantes("ventas", date(2017, 1, 18), 28, ingerido)
    # También es "tardía" (fuera del plazo nominal, aunque dentro de la tolerancia) la primera
    # versión válida de las ventas del 01-14: inválidas el 01-15 y reentregadas el 01-16.
    tardios = leer_ledger(ingerido).query("es_tardio")
    assert sorted(tardios["fecha_dato"].dt.date.astype(str)) == ["2017-01-12", "2017-01-14"]


# ------------------------------------------------------------------------------ as-of


def test_historico_respeta_disponibilidad(ingerido):
    ventas = asof("ventas", date(2016, 12, 12), ingerido)
    assert ventas["fecha_dato"].max() == pd.Timestamp("2016-12-11")
    promos = asof("promociones", date(2016, 12, 12), ingerido)
    assert promos["date"].max() == pd.Timestamp("2016-12-22")
    assert set(asof("tiendas", date(2016, 12, 12), ingerido)["store_nbr"]) == {1, 2}


def test_ventas_de_ayer_visibles_en_el_corte(ingerido):
    corte = date(2017, 2, 1)
    fechas = set(asof("ventas", corte, ingerido)["date"])
    assert pd.Timestamp("2017-01-31") in fechas and pd.Timestamp(corte) not in fechas
    assert ultima_fecha_disponible("ventas", corte, ingerido) == date(2017, 1, 31)
    assert ultima_fecha_disponible("ventas", date(2016, 1, 1), ingerido) is None


def test_asof_no_trae_columnas_tecnicas_y_conserva_fechas(ingerido):
    df = asof("ventas", date(2017, 1, 10), ingerido)
    assert {"version", "origen"}.isdisjoint(df.columns)
    assert {"fecha_dato", "fecha_disponible"} <= set(df.columns)
    assert (df["fecha_disponible"] <= pd.Timestamp("2017-01-10")).all()


def test_fechas_faltantes_detecta_hueco(ingerido):
    corte = date(2017, 1, 30)
    huecos = fechas_faltantes("ventas", corte, 28, ingerido)
    assert huecos == [date(2017, 1, 22), date(2017, 1, 24)]  # inválidas sin reentrega
    assert fechas_faltantes("ventas", corte, 28, ingerido, ["01-22", "01-24"]) == []
    # transacciones: el 01-10 nunca llega
    assert date(2017, 1, 10) in fechas_faltantes("transacciones", corte, 28, ingerido)


def test_asof_sin_leakage(bandeja_sintetica, cfg_fuentes, cfg_validacion, tmp_path):
    """Ingerir toda la bandeja o solo lo entregado hasta T da el mismo `asof(f, T)`."""
    historico, bandeja = bandeja_sintetica
    completa = preparar_data(tmp_path / "completa", historico)
    ingestar(FIN, completa, bandeja, cfg_fuentes, cfg_validacion)
    # T: justo antes de una corrección, el día de la corrección, tardío, alta de tienda, etc.
    for t in [
        date(2017, 1, 5),
        date(2017, 1, 8),
        date(2017, 1, 9),
        date(2017, 1, 17),
        date(2017, 1, 18),
        date(2017, 1, 19),
        date(2017, 1, 20),
        date(2017, 2, 15),
    ]:
        truncada = tmp_path / f"trunc_{t}"
        shutil.copytree(bandeja, truncada, ignore=shutil.ignore_patterns(*_posteriores(bandeja, t)))
        dd = preparar_data(tmp_path / f"data_{t}", historico)
        ingestar(t, dd, truncada, cfg_fuentes, cfg_validacion)
        for fuente in cfg_fuentes.fuentes:
            pd.testing.assert_frame_equal(
                asof(fuente, t, completa), asof(fuente, t, dd), obj=f"{fuente}@{t}"
            )


def _posteriores(bandeja: Path, t: date) -> list[str]:
    return [p.name for p in bandeja.iterdir() if p.is_dir() and p.name > t.isoformat()]
