# Estado de las fases

La skill `lab1-fases` usa este archivo para saber cuál es la siguiente fase. Se actualiza al cerrar
cada fase, en el mismo PR.

| Fase | Rama | Estado | PR | Notas |
|---|---|---|---|---|
| 0 — Fundaciones | `feat/setup` | ✅ Hecha | #1 | Repo, venv, CI (`lint-y-pruebas`), `main` protegida, CLAUDE.md |
| 1 — DVC + DagsHub | `feat/dvc` | ✅ Hecha | #2 | DagsHub no permite lectura anónima → los docentes necesitan token |
| 2 — Simulador de bandeja | `feat/bandeja-sim` | ✅ Hecha | #3 | `data/historico` + `bandeja_sim` en DVC; 14 escenarios |
| 3 — Ingesta, ledger, validación, as-of | `feat/ingesta` | ✅ Hecha | #6 | 853 archivos: 847 válidos, 5 cuarentena, 1 duplicado; simulador corregido (promos tienda 52) |
| 4 — Features, baseline, backtest, pedido | `feat/features-baseline` | ✅ Hecha | #7 | Baseline en el corte 2017-08-14: WAPE 0.143, cobertura P10–P90 84.3%, fill rate 97.4% |
| 5 — LightGBM, registro, publicación offline | `feat/lgbm` | ✅ Hecha | #8 | LightGBM vs baseline (corte 2017-08-14): WAPE 0.121 vs 0.143, costo -20.4%; champion inicial promovido el 2017-01-02; variante semanal descartada (+9.1% costo) |
| 6 — Airflow 3 en Docker | `feat/airflow` | ✅ Hecha | PR_F6 | Docker verificado (ventana 2017-01-02→03-20): 114 runs en verde, 27 commits en `publicaciones`, re-ejecución sin cambios (mismo hash). Falta backfill completo y capturas de la UI (fase 8) |
| 7 — Monitoreo, correcciones, e2e | `feat/monitoreo` | ✅ Hecha | #10 | Seguimiento por corte (as-of), revisiones por corrección (`datos_hasta`), alerta de degradación (solo advertencia), reporte MD+PNG, 11 pruebas e2e. Real (2017-01-02→08-14): WAPE por corte 0.107–0.196 (salvo 01-02: 0.563), 3 revisiones emitidas, DAG verificado en Docker |
| 8 — Reproducibilidad, docs, entrega | `feat/docs` | ⏳ Pendiente | | |

## Decisiones tomadas durante la ejecución

Registrar aquí (una línea por decisión) lo que el usuario decidió en cada fase, además de
documentarlo en `DECISIONES.md`.

- F2: bandeja con una carpeta por fecha de entrega; promociones como fuente separada (D−10).
- F3: columna faltante → cuarentena y extra → advertencia; ventas incompletas → advertencia; histórico con la regla de cada fuente; almacén limpio = un parquet por fuente reconstruido.
- F3: se corrigió el simulador para que no entregue promociones de la tienda 52 antes de su maestro (mantiene tienda desconocida = cuarentena).
- F4: costos en tres grupos (perecederos τ=0.40, no perecederos τ=0.91, default τ=0.67); cobertura 7 días con lead time 0; pedido = suma de cuantiles diarios τ; entrenamiento con las últimas 52 semanas de orígenes.
- F4: τ se redondea a 2 decimales (el modelo se entrena en el mismo cuantil que usa el pedido).
- F5: criterio de reemplazo multicriterio (`config/promotion.yaml`): costo total baja ≥ 3%, WAPE no empeora > 1%, cobertura P10–P90 en [0.70, 0.90], ninguna familia con > 5% del volumen empeora su costo > 10%, checks técnicos.
- F5: reentrenamiento mensual (primer lunes del mes) + manual; el pronóstico semanal usa el champion vigente.
- F5: backtest de LightGBM con los 8 orígenes (un origen tarda ~1 min; el backtest completo cabe en el límite de ~20 min).
- F5: variante "cuantil de demanda semanal" entrenada y comparada; el pedido por defecto no cambia (resultado en `DECISIONES.md` y `reports/comparacion_modelos.md`).
- F6: Airflow 3.3.2 fijada (`apache/airflow:3.3.2-python3.11`), `LocalExecutor`.
- F6: periodo no publicado = `.env` con `BANDEJA_PATH`, `REPOSICION_INICIO`, `REPOSICION_FIN`; DAGs con `catchup=True` entre esas fechas (basta despausarlos o `airflow backfill create`).
- F6: `push_remoto: auto` (`config/operacion.yaml`): con `GITHUB_TOKEN` hace push de `publicaciones`, con `DAGSHUB_TOKEN` hace `dvc push`; sin credenciales, commit local + warning, sin fallar.
- F6: cuatro DAGs con schedule por tiempo (sin Assets). Se agregó la tarea `asegurar_champion` al DAG semanal para que el backfill no dependa del orden entre DAGs.
- F6: reentrenamiento mensual (primer lunes del mes, `short_circuit`) + manual (`forzar=true`); el pronóstico semanal usa el champion vigente.
- F7: corrección que afecta un publicado: nunca se reescribe; el seguimiento se recalcula con el dato corregido y, si el corte sigue vigente, se emite `rev=N+1` con `emitido_en` = corte de detección (`reemitir_si_corrige: true` en `config/monitoreo.yaml`); `emitir_revisiones` va en el DAG de seguimiento.
- F7: reporte de seguimiento en Markdown + PNG (matplotlib, backend Agg) por corte de evaluación en `data/monitoring/reportes/`; la copia a `reports/seguimiento.md` se hace en la fase 8 (`seguimiento.publicar_reporte_reciente`).
- F7: alerta de degradación solo como advertencia (reporte y log): WAPE móvil de 4 cortes > 1.2 × WAPE del backtest del champion; no reentrena automáticamente.
