"""Seguimiento semanal (lunes): compara lo publicado con las ventas reales (fase 7)."""

from airflow.sdk import dag, task

from _comun import (
    ARGUMENTOS,
    ARGUMENTOS_REMOTO,
    END_DATE,
    POOL,
    START_DATE,
    bandeja,
    config,
    corte,
    dir_data,
    publicar_remoto,
    versionar,
)
from reposicion import orquestacion as orq


@dag(
    dag_id="seguimiento_desempeno",
    schedule="0 7 * * 1",
    start_date=START_DATE,
    end_date=END_DATE,
    catchup=True,
    max_active_runs=1,
    default_args=ARGUMENTOS,
    tags=["reposicion", "monitoreo"],
    doc_md=__doc__,
)
def seguimiento_desempeno():
    @task(pool=POOL)
    def asegurar_ingesta() -> dict:
        from dataclasses import asdict

        return asdict(orq.asegurar_ingesta(corte(), dir_data(), bandeja(), config()))

    @task(pool=POOL)
    def evaluar_publicados() -> dict:
        """Implementado en la fase 7 (por ahora deja una señal clara en el log)."""
        return orq.evaluar_publicados(corte(), dir_data())

    @task(pool=POOL)
    def versionar_seguimiento() -> str | None:
        return versionar("seguimiento")

    @task(pool=POOL, **ARGUMENTOS_REMOTO)
    def publicar_remoto_seguimiento() -> dict:
        return publicar_remoto()

    (
        asegurar_ingesta()
        >> evaluar_publicados()
        >> versionar_seguimiento()
        >> publicar_remoto_seguimiento()
    )


seguimiento_desempeno()
