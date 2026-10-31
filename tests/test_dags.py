"""Los DAGs de Airflow cargan sin errores y cumplen el contrato de la fase 6.

Se omite si Airflow no está instalado (el job `dags` del CI lo instala con sus constraints).
"""

import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

pytest.importorskip("airflow")
os.environ.setdefault("AIRFLOW__CORE__LOAD_EXAMPLES", "false")  # solo los DAGs del repo

from airflow.models import DagBag  # noqa: E402

from reposicion.operacion import cargar_operacion  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]
DAGS = {
    "ingesta_validacion": "0 5 * * *",
    "pronostico_semanal": "0 6 * * 1",
    "seguimiento_desempeno": "0 7 * * 1",
    "entrenamiento": "0 4 * * 1",
}
# Tareas que escriben en data/, DVC o git → pool `escritura_datos`
SIN_POOL = {"reportar_calidad", "es_momento"}


@pytest.fixture(scope="module")
def dagbag() -> DagBag:
    # Airflow pone la carpeta de DAGs en sys.path al analizarlos; aquí se hace a mano (`_comun`).
    sys.path.insert(0, str(RAIZ / "dags"))
    return DagBag(dag_folder=str(RAIZ / "dags"))


def test_sin_errores_de_import(dagbag):
    assert dagbag.import_errors == {}


def test_estan_los_cuatro_dags(dagbag):
    assert set(dagbag.dags) == set(DAGS)


@pytest.mark.parametrize("dag_id", DAGS)
def test_configuracion_comun(dagbag, dag_id):
    dag = dagbag.dags[dag_id]
    op = cargar_operacion(RAIZ / "config" / "operacion.yaml")
    assert dag.catchup is True
    assert dag.max_active_runs == 1
    assert dag.start_date == datetime(op.inicio.year, op.inicio.month, op.inicio.day, tzinfo=UTC)
    assert dag.end_date.date() == op.fin
    # CronTriggerTimetable: `logical_date` es el instante del disparo (= la fecha de corte)
    assert type(dag.timetable).__name__ == "CronTriggerTimetable"
    assert dag.timetable.expression == DAGS[dag_id]


@pytest.mark.parametrize("dag_id", DAGS)
def test_las_tareas_de_escritura_usan_el_pool(dagbag, dag_id):
    for tarea in dagbag.dags[dag_id].tasks:
        if tarea.task_id in SIN_POOL:
            continue
        assert tarea.pool == "escritura_datos", f"{dag_id}.{tarea.task_id}"


@pytest.mark.parametrize("dag_id", DAGS)
def test_reintentos_solo_en_io_remoto(dagbag, dag_id):
    for tarea in dagbag.dags[dag_id].tasks:
        esperado = 2 if tarea.task_id.startswith("publicar_remoto") else 0
        assert tarea.retries == esperado, f"{dag_id}.{tarea.task_id}"


def test_orden_de_las_tareas(dagbag):
    def orden(dag_id: str) -> list[str]:
        dag = dagbag.dags[dag_id]
        return [t.task_id for t in dag.topological_sort()]

    assert orden("pronostico_semanal") == [
        "asegurar_ingesta",
        "asegurar_champion",
        "verificar_datos",
        "pronosticar",
        "versionar_pronostico",
        "publicar_remoto_pronostico",
    ]
    assert orden("entrenamiento")[:3] == ["es_momento", "asegurar_ingesta", "entrenar_y_evaluar"]
    assert orden("ingesta_validacion") == ["ingestar", "reportar_calidad"]
    # La ingesta va antes de todo lo que lee `asof(corte)`.
    assert orden("seguimiento_desempeno")[0] == "asegurar_ingesta"
