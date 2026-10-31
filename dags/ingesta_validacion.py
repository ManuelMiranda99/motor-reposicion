"""Ingesta diaria: bandeja → ledger → almacén limpio, con reporte de calidad."""

from dataclasses import asdict

from airflow.sdk import dag, task

from _comun import (
    ARGUMENTOS,
    END_DATE,
    POOL,
    START_DATE,
    bandeja,
    config,
    corte,
    dir_data,
)
from reposicion import orquestacion as orq


@dag(
    dag_id="ingesta_validacion",
    schedule="0 5 * * *",
    start_date=START_DATE,
    end_date=END_DATE,
    catchup=True,
    max_active_runs=1,
    default_args=ARGUMENTOS,
    tags=["reposicion", "ingesta"],
    doc_md=__doc__,
)
def ingesta_validacion():
    @task(pool=POOL)
    def ingestar() -> dict:
        """Ingiere lo entregado hasta el corte (idempotente)."""
        return asdict(orq.asegurar_ingesta(corte(), dir_data(), bandeja(), config()))

    @task
    def reportar_calidad(resumen: dict) -> dict:
        """Resume en el log y en XCom lo entregado ese día; la cuarentena no hace fallar."""
        return orq.reportar_calidad(corte(), dir_data())

    reportar_calidad(ingestar())


ingesta_validacion()
