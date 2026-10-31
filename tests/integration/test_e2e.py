"""Pruebas end-to-end sin Airflow: ingesta → pronóstico → revisiones → seguimiento por corte.

Usan la bandeja sintética (3 tiendas × 2 familias, enero–febrero de 2017) y el baseline (sin
champion registrado, el pronóstico entrena el baseline en el momento): nunca leen `data/` real.
Cada ciclo es la secuencia de los DAGs de un lunes (`corte`).
"""

import json
import shutil
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

from reposicion.almacen import leer_ledger, leer_parquet
from reposicion.asof import asof
from reposicion.ingesta import ingestar
from reposicion.parametros import Configs
from reposicion.publicacion import directorio_publicacion, pronosticar_corte
from reposicion.revisiones import emitir_revisiones
from reposicion.seguimiento import evaluar_publicados
from reposicion.simulador import generar
from tests.sinteticos import crear_config, hashes_dir, preparar_data
from tests.unit.test_backtest import NEGOCIO, cfg_modelo

pytestmark = pytest.mark.integration

CORTES = [date(2017, 1, 2) + timedelta(days=7 * k) for k in range(9)]  # 01-02 … 02-27


def config_e2e():
    """Escenarios por defecto + corrección de petróleo + ventas que nunca llegan."""
    esc = crear_config().escenarios.model_dump(mode="json")
    esc["correcciones"].append(
        {
            "fuente": "petroleo",
            "fecha_dato": "2017-01-18",
            "fecha_entrega": "2017-01-25",
            "fraccion_filas": 1.0,
            "factor": 1.05,
        }
    )
    esc["faltantes"].append({"fuente": "ventas", "fecha_dato": "2017-02-08"})
    return crear_config(escenarios=esc)


@pytest.fixture(scope="module")
def entorno(kaggle_sintetico, tmp_path_factory):
    """Bandeja completa + configuraciones; fija el commit para que los manifiestos sean estables."""
    from reposicion.fuentes import cargar_fuentes
    from reposicion.validacion import cargar_validacion
    from tests.conftest import RAIZ

    raiz = tmp_path_factory.mktemp("e2e")
    cfg = config_e2e()
    generar(kaggle_sintetico, cfg, raiz / "historico", raiz / "bandeja")
    fuentes = cargar_fuentes(RAIZ / "config" / "sources.yaml")
    validacion = cargar_validacion(RAIZ / "config" / "validation.yaml")
    return {
        "raiz": raiz,
        "simulador": cfg,
        "historico": raiz / "historico",
        "bandeja": raiz / "bandeja",
        "cfgs": Configs(cfg_modelo(), NEGOCIO, fuentes, validacion),
        "kaggle": kaggle_sintetico,
    }


@pytest.fixture(scope="module", autouse=True)
def _commit_fijo():
    """Mismo `git_commit` en todos los manifiestos (también en las fixtures de módulo)."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("REPOSICION_GIT_COMMIT", "e2e")
        yield


def ciclo(corte: date, dir_data: Path, bandeja: Path, cfgs: Configs) -> None:
    """Las tareas semanales de los DAGs, en su orden."""
    ingestar(corte, dir_data, bandeja, cfgs.fuentes, cfgs.validacion)
    pronosticar_corte(corte, dir_data, cfgs)
    emitir_revisiones(corte, dir_data, cfgs)
    evaluar_publicados(corte, dir_data, cfgs)


def correr(entorno, destino: Path, bandeja: Path | None = None) -> Path:
    datos = preparar_data(destino, entorno["historico"])
    for corte in CORTES:
        ciclo(corte, datos, bandeja or entorno["bandeja"], entorno["cfgs"])
    return datos


@pytest.fixture(scope="module")
def corrida(entorno, tmp_path_factory) -> Path:
    """Backfill completo (todos los cortes con la bandeja completa)."""
    return correr(entorno, tmp_path_factory.mktemp("corrida") / "data")


def leer_manifiesto(datos: Path, corte: date, rev: int = 1) -> dict:
    ruta = directorio_publicacion(datos, corte, rev) / "manifest.json"
    return json.loads(ruta.read_text())


def revisiones(datos: Path, corte: date) -> list[int]:
    base = directorio_publicacion(datos, corte, 1).parent
    return sorted(int(p.name.removeprefix("rev=")) for p in base.glob("rev=*"))


def test_e2e_publica_todos_los_cortes_y_el_seguimiento(corrida):
    for corte in CORTES:
        assert (directorio_publicacion(corrida, corte, 1) / "pronostico.parquet").exists()
        assert (corrida / "monitoring" / f"corte={corte}" / "resumen.json").exists()
        assert (corrida / "monitoring" / "reportes" / f"{corte}.md").exists()
    ultimo = leer_parquet(
        corrida / "monitoring" / f"corte={CORTES[-1]}" / "metricas_por_corte.parquet"
    )
    assert set(ultimo["corte"].dt.date) == set(CORTES)
    completos = ultimo[ultimo["estado"] == "completo"]
    assert len(completos) > 0 and completos["wape"].between(0, 5).all()


def test_e2e_idempotente(corrida, entorno, tmp_path):
    """Repetir toda la secuencia sobre el mismo `dir_data` no cambia ni un byte."""
    datos = tmp_path / "data"
    shutil.copytree(corrida, datos)
    antes = hashes_dir(datos)
    for corte in CORTES:
        ciclo(corte, datos, entorno["bandeja"], entorno["cfgs"])
    assert hashes_dir(datos) == antes
    assert not list(datos.rglob("*.tmp"))


def test_e2e_backfill_igual_a_operacion(corrida, entorno, tmp_path):
    """Correr los cortes con la bandeja completa = correrlos "en vivo" (bandeja ampliada)."""
    vivo = tmp_path / "bandeja_viva"
    datos = preparar_data(tmp_path / "data", entorno["historico"])
    for corte in CORTES:
        # la bandeja crece hasta la entrega del corte (el simulador no altera lo ya generado)
        cfg = entorno["simulador"].model_copy(update={"hasta": corte})
        generar(entorno["kaggle"], cfg, tmp_path / "hist_descartable", vivo)
        ciclo(corte, datos, vivo, entorno["cfgs"])
    assert hashes_dir(datos) == hashes_dir(corrida)


def test_e2e_sin_leakage(corrida, entorno, tmp_path):
    """Los publicados de un corte no cambian aunque la bandeja ya tenga datos posteriores."""
    datos = preparar_data(tmp_path / "data", entorno["historico"])
    ingestar(date(2017, 3, 1), datos, entorno["bandeja"], entorno["cfgs"].fuentes,
             entorno["cfgs"].validacion)  # fmt: skip
    for corte in (date(2017, 1, 16), date(2017, 1, 23), date(2017, 2, 13)):
        pronosticar_corte(corte, datos, entorno["cfgs"])
        assert hashes_dir(directorio_publicacion(datos, corte, 1)) == hashes_dir(
            directorio_publicacion(corrida, corte, 1)
        ), corte


def test_e2e_correccion_de_ventas_genera_revision_y_recalcula_el_seguimiento(corrida):
    p = date(2017, 1, 2)  # publicado antes de la entrega (01-09) de la corrección del 01-05
    assert revisiones(corrida, p) == [1, 2]
    m = leer_manifiesto(corrida, p, 2)
    assert m["emitido_en"] == m["datos_hasta"] == "2017-01-09" and m["revision_de"] == 1
    assert "ventas 2017-01-05" in m["motivo"]
    assert "emitido_en" not in leer_manifiesto(corrida, p, 1)  # rev=1 intacta
    # el seguimiento del 01-09 usa la versión 2 de las ventas del 01-05 (y de ninguna otra manera)
    v = asof("ventas", date(2017, 1, 9), corrida)
    v1 = asof("ventas", date(2017, 1, 8), corrida)
    dia = pd.Timestamp("2017-01-05")
    assert not v[v["fecha_dato"] == dia]["sales"].equals(v1[v1["fecha_dato"] == dia]["sales"])
    pron = leer_parquet(directorio_publicacion(corrida, p, 1) / "pronostico.parquet")
    pron = pron[pron["fecha_objetivo"] == dia].merge(
        v[v["fecha_dato"] == dia], left_on=["store_nbr", "family"], right_on=["store_nbr", "family"]
    )
    esperado = (pron["q0.50"] - pron["sales"]).abs().sum() / pron["sales"].sum()
    por_h = leer_parquet(corrida / "monitoring" / "corte=2017-01-09" / "metricas_por_h.parquet")
    fila = por_h[(por_h["corte"] == pd.Timestamp(p)) & (por_h["revision"] == 1) & (por_h["h"] == 4)]
    assert fila.iloc[0]["wape"] == pytest.approx(esperado)


def test_e2e_correccion_de_petroleo_genera_revision(corrida):
    p = date(2017, 1, 23)  # la corrección del petróleo del 01-18 se entrega el 01-25
    assert revisiones(corrida, p) == [1, 2]
    assert "petroleo 2017-01-18 (entrega 2017-01-25)" in leer_manifiesto(corrida, p, 2)["motivo"]
    assert leer_manifiesto(corrida, p, 2)["emitido_en"] == "2017-01-30"


def test_e2e_tardio_el_corte_anterior_no_lo_vio_y_el_siguiente_si(corrida):
    # ventas del 01-12, entregadas el 01-18 (esperadas el 01-13)
    antes = leer_manifiesto(corrida, date(2017, 1, 16))
    assert antes["calidad"] == "degradada" and any("2017-01-12" in a for a in antes["advertencias"])
    despues = leer_manifiesto(corrida, date(2017, 1, 23))
    assert not any("2017-01-12" in a for a in despues["advertencias"])
    ledger = leer_ledger(corrida)
    fila = ledger[(ledger["fuente"] == "ventas") & (ledger["fecha_dato"] == "2017-01-12")]
    assert fila["es_tardio"].tolist() == [True]
    # el corte 01-16 sigue vigente el 01-23: se emite su revisión, que sí ve el dato
    assert revisiones(corrida, date(2017, 1, 16)) == [1, 2]
    assert "tardío" in leer_manifiesto(corrida, date(2017, 1, 16), 2)["motivo"]
    # el 01-09 ya no estaba vigente: sin revisión
    assert revisiones(corrida, date(2017, 1, 9)) == [1]


def test_e2e_faltante_no_falla_y_queda_como_real_pendiente(corrida):
    # transacciones 01-10 y ventas 02-08 nunca llegan: todos los cortes se publicaron igual
    assert all((directorio_publicacion(corrida, c, 1)).exists() for c in CORTES)
    assert leer_manifiesto(corrida, date(2017, 2, 13))["calidad"] == "degradada"
    por_corte = leer_parquet(
        corrida / "monitoring" / "corte=2017-02-27" / "metricas_por_corte.parquet"
    )
    fila = por_corte[(por_corte["corte"] == "2017-02-06") & (por_corte["revision"] == 1)].iloc[0]
    assert fila["dias_sin_real"] == "2017-02-08" and fila["estado"] == "parcial"
    md = (corrida / "monitoring" / "reportes" / "2017-02-27.md").read_text()
    assert "sin real el 2017-02-08" in md


def test_e2e_duplicado_se_ignora_y_no_genera_revision(corrida):
    ledger = leer_ledger(corrida)
    dup = ledger[(ledger["fuente"] == "ventas") & (ledger["fecha_dato"] == "2017-01-06")]
    assert sorted(dup["estado"]) == ["duplicado", "valido"]
    assert not dup["es_correccion"].any() and not dup["es_tardio"].any()


def test_e2e_invalido_va_a_cuarentena_y_la_reentrega_se_incorpora(corrida):
    ledger = leer_ledger(corrida)
    f = ledger[(ledger["fuente"] == "ventas") & (ledger["fecha_dato"] == "2017-01-14")]
    assert f.sort_values("fecha_entrega")["estado"].tolist() == ["cuarentena", "valido"]
    assert not f["es_correccion"].any()
    ventas = asof("ventas", date(2017, 1, 16), corrida)
    del_dia = ventas[ventas["fecha_dato"] == "2017-01-14"]
    assert len(del_dia) > 0 and (del_dia["sales"] >= 0).all()  # sin la versión inválida
    # ningún publicado contiene datos de la cuarentena (cuantiles válidos)
    pron = leer_parquet(
        directorio_publicacion(corrida, date(2017, 1, 16), 1) / "pronostico.parquet"
    )
    assert (pron["q0.50"] >= 0).all()


def test_e2e_alta_de_tienda(corrida):
    # la tienda 3 tiene maestro desde el 01-20: el corte del 01-16 no la pronostica
    antes = leer_parquet(
        directorio_publicacion(corrida, date(2017, 1, 16), 1) / "pronostico.parquet"
    )
    despues = leer_parquet(
        directorio_publicacion(corrida, date(2017, 1, 23), 1) / "pronostico.parquet"
    )
    assert 3 not in set(antes["store_nbr"]) and 3 in set(despues["store_nbr"])
