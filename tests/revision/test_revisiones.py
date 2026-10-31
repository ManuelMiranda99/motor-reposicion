"""Revisión independiente — correcciones, revisiones `rev=N` y orden de ejecución.

Cada prueba afirma el comportamiento CORRECTO esperado; si falla, demuestra el hallazgo descrito en
`tests/revision/INFORME.md`.
"""

from __future__ import annotations

import os
from datetime import date

import pandas as pd
import pytest

from reposicion.asof import asof
from reposicion.correcciones import cortes_afectados
from reposicion.features import construir_features
from reposicion.ingesta import ingestar
from reposicion.parametros import ConfigModelo
from reposicion.publicacion import directorio_publicacion, pronosticar_corte
from reposicion.revisiones import emitir_revisiones
from reposicion.seguimiento import listar_publicaciones
from reposicion.simulador import generar
from tests.datos_modelo import datos_sinteticos
from tests.revision.comun import configs, nuevo_dir_data
from tests.sinteticos import crear_config


def revisiones(dir_data, corte: date) -> list[str]:
    base = directorio_publicacion(dir_data, corte, 1).parent
    return sorted(p.name for p in base.glob("rev=*"))


# --------------------------------- H-REV-1 dato que llega después del corte sin ser "tardío"
@pytest.mark.parametrize(
    "escenarios",
    [
        pytest.param(  # inválido el lunes 01-30 (D+1), reentrega válida el martes 01-31
            {
                "invalidos": [
                    {
                        "fuente": "ventas",
                        "fecha_dato": "2017-01-29",
                        "defecto": "ventas_negativas",
                        "correccion_entrega": "2017-01-31",
                    }
                ]
            },
            id="reentrega_tras_cuarentena",
        ),
        pytest.param(  # llega el martes 01-31: dentro de la tolerancia (D+1+2 = 02-01)
            {
                "tardios": [
                    {"fuente": "ventas", "fecha_dato": "2017-01-29", "fecha_entrega": "2017-01-31"}
                ]
            },
            id="retraso_tolerado",
        ),
    ],
)
def test_dato_que_cruza_un_corte_dentro_de_la_tolerancia_genera_revision(
    escenarios, kaggle_sintetico, cfg_fuentes, cfg_validacion, tmp_path, monkeypatch
):
    """Las ventas del domingo 01-29 no estaban en el corte del lunes 01-30 (en cuarentena o aún no
    llegaban) y llegan el martes 01-31. Como la primera versión válida llega dentro de la tolerancia
    (`es_tardio=False`) y no es corrección (`es_correccion=False`), `correcciones_entre` no la
    considera y el corte 01-30, publicado con un hueco en `lag_1`, nunca se revisa."""
    monkeypatch.setenv("REPOSICION_GIT_COMMIT", "revision")
    raiz = tmp_path / "sim"
    generar(kaggle_sintetico, crear_config(escenarios=escenarios), raiz / "hist", raiz / "bandeja")
    datos = nuevo_dir_data(raiz / "hist", tmp_path / "data")
    cfgs = configs(cfg_fuentes, cfg_validacion)
    corte = date(2017, 1, 30)

    ingestar(corte, datos, raiz / "bandeja", cfg_fuentes, cfg_validacion)
    pronosticar_corte(corte, datos, cfgs)
    visto = set(asof("ventas", corte, datos)["fecha_dato"].dt.date)
    assert date(2017, 1, 29) not in visto  # el corte se publicó sin el dato del 01-29

    ingestar(date(2017, 2, 6), datos, raiz / "bandeja", cfg_fuentes, cfg_validacion)
    assert date(2017, 1, 29) in set(asof("ventas", date(2017, 2, 6), datos)["fecha_dato"].dt.date)
    emitir_revisiones(date(2017, 2, 6), datos, cfgs)
    assert revisiones(datos, corte) == ["rev=1", "rev=2"]


# ------------------------------------- H-REV-2 el resultado depende del orden entre DAGs
@pytest.fixture
def datos_correccion(bandeja_sintetica, cfg_fuentes, cfg_validacion, tmp_path, monkeypatch):
    """Bandeja sintética estándar: corrección de ventas del 01-05 entregada el 01-09."""
    monkeypatch.setenv("REPOSICION_GIT_COMMIT", "revision")
    historico, bandeja = bandeja_sintetica
    datos = nuevo_dir_data(historico, tmp_path / "data")
    ingestar(date(2017, 1, 9), datos, bandeja, cfg_fuentes, cfg_validacion)
    return datos


def test_revision_no_depende_del_orden_seguimiento_pronostico(
    datos_correccion, cfg_fuentes, cfg_validacion
):
    """En un backfill los DAGs `pronostico_semanal` y `seguimiento_desempeno` no tienen orden entre
    sí. Si el seguimiento del 01-09 corre ANTES de que se publique el corte 01-02, no hay nada que
    revisar; luego se publica rev=1 (as-of 01-02, sin la corrección) y la revisión no se emite
    nunca (la ventana del seguimiento siguiente ya no incluye la corrección). Con el orden inverso
    sí existe rev=2: el resultado del backfill depende del scheduler."""
    cfgs = configs(cfg_fuentes, cfg_validacion)
    p, evaluacion = date(2017, 1, 2), date(2017, 1, 9)
    emitir_revisiones(evaluacion, datos_correccion, cfgs)  # seguimiento 01-09 se adelanta
    pronosticar_corte(p, datos_correccion, cfgs)  # pronóstico 01-02 corre después
    emitir_revisiones(date(2017, 1, 16), datos_correccion, cfgs)  # siguiente seguimiento
    assert revisiones(datos_correccion, p) == ["rev=1", "rev=2"]


# ---------------------------------- H-REV-3 restos de una escritura interrumpida (`rev=N.tmp`)
@pytest.fixture
def revision_interrumpida(datos_correccion, cfg_fuentes, cfg_validacion, monkeypatch):
    """Publica el corte 01-02 y simula que el worker muere justo antes del `os.replace` de rev=2."""
    cfgs = configs(cfg_fuentes, cfg_validacion)
    pronosticar_corte(date(2017, 1, 2), datos_correccion, cfgs)
    real = os.replace

    def muere(src, dst):
        if str(dst).endswith("rev=2"):
            raise KeyboardInterrupt("simulación: el worker muere antes del os.replace")
        return real(src, dst)

    monkeypatch.setattr(os, "replace", muere)
    with pytest.raises(KeyboardInterrupt):
        emitir_revisiones(date(2017, 1, 9), datos_correccion, cfgs)
    monkeypatch.setattr(os, "replace", real)
    return datos_correccion, cfgs


def test_revision_interrumpida_se_puede_reintentar(revision_interrumpida):
    """`pronosticar_corte` escribe `rev=N.tmp/manifest.json` y luego `os.replace`. Si el proceso
    muere entre ambos pasos queda `rev=2.tmp/manifest.json`; `_revisiones_de` hace `int("2.tmp")` y
    el reintento de `emitir_revisiones` falla SIEMPRE con `ValueError` (hay que limpiar a mano)."""
    datos, cfgs = revision_interrumpida
    emitir_revisiones(date(2017, 1, 9), datos, cfgs)  # reintento
    assert revisiones(datos, date(2017, 1, 2))[:2] == ["rev=1", "rev=2"]


def test_publicacion_interrumpida_no_cuenta_como_publicada(revision_interrumpida):
    """`listar_publicaciones` (seguimiento) y `cortes_publicados` usan `rev=*/manifest.json`, que
    también encuentra `rev=2.tmp/`: el seguimiento evalúa una publicación que nunca se completó."""
    datos, _ = revision_interrumpida
    pubs = listar_publicaciones(datos, date(2017, 1, 9))
    assert [x["ruta"].name for x in pubs] == ["rev=1"]


# --------------------------- H-REV-4 corrección de feriados que afecta la vista hacia adelante
def test_correccion_de_feriados_marca_los_cortes_cuya_vista_adelante_cambia():
    """Las features miran feriados hasta `TOPE_DIAS_FERIADO` (30) días después del último día
    objetivo, pero `cortes_afectados` solo marca P si `fecha_dato <= P + h - 1`, y en feriados
    `fecha_dato` es el INICIO del trimestre. Una corrección (o llegada tardía) del archivo del
    2º trimestre que agrega un feriado el 04-03 cambia `dias_al_feriado` del corte 03-06, pero ese
    corte no se marca como afectado."""
    cfg = ConfigModelo(cuantiles_reporte=[0.5])
    from reposicion.fuentes import cargar_fuentes
    from tests.conftest import RAIZ

    fuentes = cargar_fuentes(RAIZ / "config" / "sources.yaml")
    corte = date(2017, 3, 6)
    datos = datos_sinteticos()
    datos["feriados"] = datos["feriados"].iloc[0:0]  # sin feriados cercanos al corte
    sin = construir_features(datos, [corte], cfg, fuentes, con_objetivo=False)
    con_feriado = dict(datos)
    extra = pd.DataFrame(
        [(pd.Timestamp("2017-04-03"), "Holiday", "National", "Ecuador", "Corregido", False)],
        columns=datos["feriados"].columns,
    )
    con_feriado["feriados"] = pd.concat([datos["feriados"], extra], ignore_index=True)
    con = construir_features(con_feriado, [corte], cfg, fuentes, con_objetivo=False)
    assert not sin["dias_al_feriado"].equals(con["dias_al_feriado"])  # la feature sí cambia

    correccion = pd.DataFrame(
        {
            "fuente": ["feriados"],
            "fecha_dato": [pd.Timestamp("2017-04-01")],  # inicio del trimestre del archivo
            "fecha_entrega": [pd.Timestamp("2017-03-08")],
        }
    )
    afectados = cortes_afectados(correccion, [corte], cfg.horizonte_dias, 364)
    assert corte in afectados
