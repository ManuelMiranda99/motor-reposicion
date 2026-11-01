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
| 6 — Airflow 3 en Docker | `feat/airflow` | ✅ Hecha | #9 | Docker verificado (ventana 2017-01-02→03-20): 114 runs en verde, 27 commits en `publicaciones`, re-ejecución sin cambios (mismo hash). Falta backfill completo y capturas de la UI (fase 8) |
| 7 — Monitoreo, correcciones, e2e | `feat/monitoreo` | ✅ Hecha | #10 | Seguimiento por corte (as-of), revisiones por corrección (`datos_hasta`), alerta de degradación (solo advertencia), reporte MD+PNG, 11 pruebas e2e. Real (2017-01-02→08-14): WAPE por corte 0.107–0.196 (salvo 01-02: 0.563; tras la revisión independiente, 0.217), 3 revisiones emitidas, DAG verificado en Docker |
| 8 — Reproducibilidad, docs, entrega | `feat/docs` | ✅ Hecha | #11 | `reproducir` (REPRODUCIDO ✓ en 5 publicaciones, 3 con revisión), backfill completo en Docker (324 runs en verde, ~3 h 54 min; repetido tras las correcciones de la revisión independiente), `.dvc` de `data/` en main, ensayo docente con bandeja distinta, README/DECISIONES/CLAUDE.md completos. Capturas de Airflow en `reports/evidencia/` (Playwright, `tools/capturas_airflow.py`). Pendiente del usuario: tag `entrega-lab1` |

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
- F8 (decisión del usuario): el docente usa su propia cuenta de DagsHub + `tools/dvc_auth.sh` (no se migra el remoto). **Reemplazada** después (ver la última línea).
- F8 (decisión del usuario): se commitean a `main` los `.dvc` de `data/` del backfill completo (histórico, modelos, publicados, seguimiento) y se hace `dvc push`; verificado en clon limpio (`dvc status -c` limpio).
- F8 (decisión del usuario): el tag `entrega-lab1` NO se crea desde la automatización; comando: `git switch main && git pull && git tag -a entrega-lab1 -m "Entrega Laboratorio 1" && git push origin entrega-lab1`.
- F8: el primer backfill falló por hibernación del equipo (no por el código) y se repitió completo desde cero; ver `DECISIONES.md` §13.
- Revisión independiente (PR #12 código + PR #13 datos): corregidos A1–A3 y M1–M6 (DECISIONES §14); B1–B6 quedaron como `xfail` y se corrigieron en el PR #14. Backfill completo repetido en Docker con el código de `fd25eca`: WAPE del corte 2017-01-02 0.563 → 0.217, WAPE global 0.1547 → 0.1407, 0 alertas, tienda 52 con pedido en 04-17 (619 vs 0), 3 revisiones, `reproducir` ✓ en 6 publicaciones. La rama `publicaciones` remota se reemplazó (decisión del usuario, force-push) con el historial de este backfill (`6d31e2d`, 74 commits), coherente con los `.dvc` de `main`.
- Hallazgos bajos B1–B6 corregidos (PR #14, DECISIONES §14 "Segunda ronda"); suite sin `xfail`. Verificación de coherencia con los datos entregados (sin escribir en `data/`): re-ingesta completa con ledger y `limpio/` idénticos, `emitir_revisiones` sin revisiones nuevas (las mismas 3), nuevos `checks_tecnicos` sin problemas en los 11 backtests guardados y decisiones de promoción recalculables iguales, `reproducir` ✓ en Docker (03-13 rev=1 y 02-06 rev=2). No se repitió el backfill.
- Migración del remoto DVC (decisión del usuario): DagsHub → Cloudflare R2 (bucket `lab-1`). Remoto `publico` (HTTP r2.dev, lectura anónima, por defecto) y `r2` (S3, escritura con `R2_ACCESS_KEY_ID`/`R2_SECRET_ACCESS_KEY`); 1957 objetos de todo el historial (incluida `publicaciones`) copiados; clon limpio sin credenciales: `dvc pull` completo y `dvc status -c` en sincronía. r2.dev responde 429 tras ~600 objetos → `tools/dvc_pull.sh` reintenta (~1–2 min, 2–3 intentos). DECISIONES §2.
