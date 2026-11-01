# Capturas de la UI de Airflow

Capturas del backfill entregado (2017-01-02 → 2017-08-14, Airflow 3.3.2 en Docker, fechas en UTC).
Se generan con `python tools/capturas_airflow.py` (Playwright + Chromium headless) con el stack
levantado (`docker compose up -d`, <http://localhost:8080>, usuario `airflow`, contraseña `airflow`).

| Captura | Qué muestra |
|---|---|
| [`01_dags.png`](01_dags.png) | Pestaña **Dags**: los cuatro DAGs (`entrenamiento`, `ingesta_validacion`, `pronostico_semanal`, `seguimiento_desempeno`) con sus últimos runs en verde. |
| [`02_grid_ingesta_validacion.png`](02_grid_ingesta_validacion.png) | **Grid** de `ingesta_validacion`: últimos 50 runs diarios (de 225), todos en verde. |
| [`03_grid_entrenamiento.png`](03_grid_entrenamiento.png) | **Grid** de `entrenamiento` (33 lunes): el primer lunes de cada mes corre completo; los demás quedan *skipped* tras `es_momento`. |
| [`04_grid_pronostico_semanal.png`](04_grid_pronostico_semanal.png) | **Grid** de `pronostico_semanal`: los 33 cortes en verde (las barras altas son los lunes que esperan al champion del mes). |
| [`05_grid_seguimiento_desempeno.png`](05_grid_seguimiento_desempeno.png) | **Grid** de `seguimiento_desempeno`: los 33 cortes en verde. |
| [`06_cuarentena.png`](06_cuarentena.png) | Run **2017-05-11** de `ingesta_validacion`, tarea `reportar_calidad`: `ventas_2017-05-10.csv` va a cuarentena por 10 valores negativos en `sales`, sin fallar el run. |
| [`07_revision_por_correccion.png`](07_revision_por_correccion.png) | Run **2017-02-13** de `seguimiento_desempeno`, tarea `emitir_revisiones`: la corrección de ventas del 02-03 emite `corte=2017-02-06/rev=2` (los cortes cuyo horizonte ya terminó no se reemiten). |
| [`08_corte_degradado.png`](08_corte_degradado.png) | Run **2017-03-13** de `pronostico_semanal`, tarea `verificar_datos`: calidad `degradada` porque falta la venta tardía del 03-09. |

Los logs de 06–08 muestran dos ejecuciones con el mismo resultado: el backfill de la fase 8 y el
backfill repetido desde cero tras las correcciones de la revisión independiente (los logs de
Airflow se conservaron entre ambos).
