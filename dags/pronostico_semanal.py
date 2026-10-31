"""Pronóstico semanal (lunes): publica el pronóstico a 14 días y el pedido sugerido."""

from airflow.sdk import dag, task
from airflow.sdk.exceptions import AirflowFailException

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
from reposicion.parametros import cargar_configs
from reposicion.publicacion import PublicacionInmutable


@dag(
    dag_id="pronostico_semanal",
    schedule="0 6 * * 1",
    start_date=START_DATE,
    end_date=END_DATE,
    catchup=True,
    max_active_runs=1,
    default_args=ARGUMENTOS,
    tags=["reposicion", "pronostico"],
    doc_md=__doc__,
)
def pronostico_semanal():
    @task(pool=POOL)
    def asegurar_ingesta() -> dict:
        """Deja la ingesta lista hasta el corte, sin depender del DAG diario."""
        from dataclasses import asdict

        return asdict(orq.asegurar_ingesta(corte(), dir_data(), bandeja(), config()))

    @task(pool=POOL)
    def asegurar_champion() -> dict:
        """El champion vigente en el corte sale del último reentrenamiento mensual (idempotente)."""
        return orq.asegurar_champion(corte(), dir_data(), bandeja(), config())

    @task(pool=POOL)
    def verificar_datos() -> dict:
        """Modo degradado: sin ventas recientes falla; huecos menores solo advierten."""
        return orq.verificar_datos(corte(), dir_data(), cargar_configs(config()))

    @task(pool=POOL)
    def pronosticar() -> str:
        """Publica rev=1 (no-op si ya existe con las mismas entradas)."""
        try:
            return orq.publicar_pronostico(corte(), dir_data(), config())
        except PublicacionInmutable as e:  # no es transitoria: no se reintenta
            raise AirflowFailException(str(e)) from e

    @task(pool=POOL)
    def versionar_pronostico() -> str | None:
        return versionar("pronostico")

    @task(pool=POOL, **ARGUMENTOS_REMOTO)
    def publicar_remoto_pronostico() -> dict:
        return publicar_remoto()

    (
        asegurar_ingesta()
        >> asegurar_champion()
        >> verificar_datos()
        >> pronosticar()
        >> versionar_pronostico()
        >> publicar_remoto_pronostico()
    )


pronostico_semanal()
