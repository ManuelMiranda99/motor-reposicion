# Capturas de la UI de Airflow (pendientes de tomar)

No se pudieron automatizar: en el entorno de desarrollo no había un navegador controlable
(Playwright/Chrome headless) y no se instaló nada global. Quien entrega debe tomarlas con el stack
levantado (`docker compose up -d`, <http://localhost:8080>, usuario `airflow`, contraseña `airflow`) y
guardarlas en esta carpeta con estos nombres:

| Archivo | Cómo obtenerla |
|---|---|
| `01_dags.png` | Pestaña **Dags**: los cuatro DAGs (`ingesta_validacion`, `entrenamiento`, `pronostico_semanal`, `seguimiento_desempeno`) con sus últimos runs en verde. |
| `02_grid_ingesta_validacion.png` | Dag `ingesta_validacion` → pestaña **Grid** (runs diarios en verde). |
| `03_grid_entrenamiento.png` | Dag `entrenamiento` → **Grid** (los lunes que no son primer lunes salen *skipped* en `es_momento`; el primer lunes de cada mes corre completo). |
| `04_grid_pronostico_semanal.png` | Dag `pronostico_semanal` → **Grid**. |
| `05_grid_seguimiento_desempeno.png` | Dag `seguimiento_desempeno` → **Grid**. |
| `06_cuarentena.png` | Un run de `ingesta_validacion` con cuarentena: p. ej. **2017-05-11** (ventas negativas del 05-10) → tarea `reportar_calidad` → **Logs** (muestra el archivo en cuarentena). Otras fechas: 2017-06-08, 2017-06-22, 2017-07-10, 2017-07-27. |
| `07_revision_por_correccion.png` | Dag `seguimiento_desempeno`, run **2017-02-13**, tarea `emitir_revisiones` → **Logs** (emite `corte=2017-02-06/rev=2` por la corrección de ventas del 02-03). |
| `08_corte_degradado.png` | Dag `pronostico_semanal`, run **2017-03-13**, tarea `verificar_datos` → **Logs** (calidad `degradada`: falta la venta tardía del 03-09). |

Para el Grid, elige la ventana completa en el selector de runs (arriba a la izquierda) y captura
la página completa. Después enlázalas desde el README (sección "Evidencias").
