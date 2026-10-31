"""Reentrenamiento mensual (primer lunes del mes) o manual: entrena el challenger y decide."""

from airflow.sdk import Param, dag, get_current_context, task

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
from reposicion.operacion import es_primer_lunes


@dag(
    dag_id="entrenamiento",
    # Todos los lunes; `es_primer_lunes` deja pasar solo el primero de cada mes. No se usa
    # "0 4 1-7 * 1": cron combina día del mes y día de la semana con O.
    schedule="0 4 * * 1",
    start_date=START_DATE,
    end_date=END_DATE,
    catchup=True,
    max_active_runs=1,
    default_args=ARGUMENTOS,
    params={
        "forzar": Param(
            False,
            type="boolean",
            description="Reentrenar aunque no sea el primer lunes del mes (disparo manual)",
        )
    },
    tags=["reposicion", "entrenamiento"],
    doc_md=__doc__,
)
def entrenamiento():
    @task.short_circuit
    def es_momento() -> bool:
        """Sigue solo el primer lunes del mes, o siempre con `forzar` (reentrenamiento manual)."""
        forzar = bool(get_current_context()["params"].get("forzar"))
        return forzar or es_primer_lunes(corte())

    @task(pool=POOL)
    def asegurar_ingesta() -> dict:
        """El entrenamiento lee `asof(corte)`: la ingesta debe estar hecha antes."""
        from dataclasses import asdict

        return asdict(orq.asegurar_ingesta(corte(), dir_data(), bandeja(), config()))

    @task(pool=POOL)
    def entrenar_y_evaluar() -> dict:
        return orq.entrenar(corte(), dir_data(), config())

    @task(pool=POOL)
    def versionar_modelo() -> str | None:
        return versionar("modelo")

    @task(pool=POOL, **ARGUMENTOS_REMOTO)
    def publicar_remoto_modelo() -> dict:
        return publicar_remoto()

    (
        es_momento()
        >> asegurar_ingesta()
        >> entrenar_y_evaluar()
        >> versionar_modelo()
        >> publicar_remoto_modelo()
    )


entrenamiento()
