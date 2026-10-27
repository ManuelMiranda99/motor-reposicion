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
| 5 — LightGBM, registro, publicación offline | `feat/lgbm` | ⏳ Pendiente | | |
| 6 — Airflow 3 en Docker | `feat/airflow` | ⏳ Pendiente | | |
| 7 — Monitoreo, correcciones, e2e | `feat/monitoreo` | ⏳ Pendiente | | |
| 8 — Reproducibilidad, docs, entrega | `feat/docs` | ⏳ Pendiente | | |

## Decisiones tomadas durante la ejecución

Registrar aquí (una línea por decisión) lo que el usuario decidió en cada fase, además de
documentarlo en `DECISIONES.md`.

- F2: bandeja con una carpeta por fecha de entrega; promociones como fuente separada (D−10).
- F3: columna faltante → cuarentena y extra → advertencia; ventas incompletas → advertencia; histórico con la regla de cada fuente; almacén limpio = un parquet por fuente reconstruido.
- F3: se corrigió el simulador para que no entregue promociones de la tienda 52 antes de su maestro (mantiene tienda desconocida = cuarentena).
- F4: costos en tres grupos (perecederos τ=0.40, no perecederos τ=0.91, default τ=0.67); cobertura 7 días con lead time 0; pedido = suma de cuantiles diarios τ; entrenamiento con las últimas 52 semanas de orígenes.
- F4: τ se redondea a 2 decimales (el modelo se entrena en el mismo cuantil que usa el pedido).
