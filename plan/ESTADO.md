# Estado de las fases

La skill `lab1-fases` usa este archivo para saber cuál es la siguiente fase. Se actualiza al cerrar
cada fase, en el mismo PR.

| Fase | Rama | Estado | PR | Notas |
|---|---|---|---|---|
| 0 — Fundaciones | `feat/setup` | ✅ Hecha | #1 | Repo, venv, CI (`lint-y-pruebas`), `main` protegida, CLAUDE.md |
| 1 — DVC + DagsHub | `feat/dvc` | ✅ Hecha | #2 | DagsHub no permite lectura anónima → los docentes necesitan token |
| 2 — Simulador de bandeja | `feat/bandeja-sim` | ✅ Hecha | #3 | `data/historico` + `bandeja_sim` en DVC; 14 escenarios |
| 3 — Ingesta, ledger, validación, as-of | `feat/ingesta` | ⏳ Pendiente | | |
| 4 — Features, baseline, backtest, pedido | `feat/features-baseline` | ⏳ Pendiente | | |
| 5 — LightGBM, registro, publicación offline | `feat/lgbm` | ⏳ Pendiente | | |
| 6 — Airflow 3 en Docker | `feat/airflow` | ⏳ Pendiente | | |
| 7 — Monitoreo, correcciones, e2e | `feat/monitoreo` | ⏳ Pendiente | | |
| 8 — Reproducibilidad, docs, entrega | `feat/docs` | ⏳ Pendiente | | |

## Decisiones tomadas durante la ejecución

Registrar aquí (una línea por decisión) lo que el usuario decidió en cada fase, además de
documentarlo en `DECISIONES.md`.

- F2: bandeja con una carpeta por fecha de entrega; promociones como fuente separada (D−10).
