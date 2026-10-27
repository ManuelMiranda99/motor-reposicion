# 06 — Fases, PRs y checklist

Cada fase es una rama `feat/...` que entra a `main` por PR con CI en verde. Las estimaciones son
orientativas para una sola persona.

## Fase 0 — Fundaciones (½ día) · `feat/setup`
- [ ] `git init`, repo en GitHub, `.gitignore` (data/, .venv/, .env, *.pdf, logs/).
- [ ] `python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements-dev.txt`.
- [ ] `pyproject.toml` (paquete `reposicion`, config de pytest y ruff), con `pip install -e .`.
- [ ] `CLAUDE.md` con las reglas del proyecto (ver abajo).
- [ ] `.github/workflows/ci.yml`: Python 3.11, pip install, ruff, pytest.
- [ ] Proteger `main`: PR obligatorio, status check `ci` requerido y sin force-push.
- [ ] Esqueleto de `README.md` y `DECISIONES.md`.

## Fase 1 — DVC + datos base (½ día) · `feat/dvc`
- [ ] Crear el repo en DagsHub conectado al de GitHub; `dvc init`; configurar el remoto con el
      endpoint de DagsHub y las credenciales en `config.local`.
- [ ] Mover los CSV a `data/kaggle/`, hacer `dvc add` y `dvc push`.
- [ ] Verificar desde un clon limpio que `dvc pull` funciona (y probar el acceso como "otro
      usuario").

## Fase 2 — Simulador de bandeja + carga histórica (1 día) · `feat/bandeja-sim`
- [ ] `tools/simulate_bandeja.py` con los escenarios de 03 (seed fija y parámetros en YAML).
- [ ] Generar `data/historico/` (≤ 2016-12-31) y `bandeja_sim/` (2017). La bandeja simulada **no**
      va dentro de `data/`, porque es "externa". Se versiona aparte con DVC para que los docentes
      puedan reproducir las pruebas.
- [ ] Pruebas del simulador (fechas, conteos, que haya correcciones).

## Fase 3 — Ingesta, ledger, validación y as-of (2 días) · `feat/ingesta`
- [ ] `ingest/` con lectura de patrones desde `sources.yaml`, sha256 y ledger.
- [ ] `validate/` con esquemas pandera, reglas duras/blandas y cuarentena.
- [ ] `asof.py` + **prueba de leakage** (bandeja completa vs. truncada → idéntico).
- [ ] Detección de correcciones y cortes afectados.
- [ ] Pruebas unitarias por cada escenario de la tabla de 03.

## Fase 4 — Features + baseline + backtest (1.5 días) · `feat/features-baseline`
- [ ] `features/` (ancladas a T y sin recursión).
- [ ] `models/baseline.py` + interfaz común `fit / predict_quantiles`.
- [ ] `backtest.py` (rolling-origin) y métricas (WAPE, RMSLE, pinball, cobertura, costo newsvendor).
- [ ] `order.py` + `business.yaml`, con una prueba de que al cambiar los costos cambia el pedido.

## Fase 5 — LightGBM + champion/challenger (1.5 días) · `feat/lgbm`
- [ ] `models/lgbm.py` con un modelo por cuantil y orden monotónico.
- [ ] Backtest comparativo → `reports/model_comparison.md`.
- [ ] `registry.py` + `promotion.yaml` + pruebas del criterio de reemplazo.
- [ ] Evaluar la variante "cuantil de demanda semanal" para el pedido y decidir.

## Fase 6 — Airflow 3 en Docker (2 días) · `feat/airflow`
- [ ] Dockerfile + `docker-compose.yaml` (LocalExecutor) + `.env.example`.
- [ ] Los 5–6 DAGs de 05, delgados.
- [ ] `versioning.py`: dvc add/push + commit/push a `publicaciones`, con pool `dvc_git`.
- [ ] `tests/test_dags.py` (DagBag sin errores de import) en CI.
- [ ] Backfill completo 2017-01 → 2017-08 en verde.

## Fase 7 — Monitoreo y reprocesamiento (1 día) · `feat/monitoreo`
- [ ] `monitor.py` + reporte HTML/MD por corte y acumulado (métricas por semana, por familia y
      cobertura).
- [ ] DAG `reprocess_corrections` y prueba end-to-end de una corrección.
- [ ] Prueba de idempotencia (dos corridas → mismos hashes).

## Fase 8 — Reproducibilidad, documentación y entrega (1 día) · `feat/docs`
- [ ] `reposicion.cli reproduce --cutoff` + sección del README "Reproducir un pronóstico pasado".
- [ ] **Ensayo de la evaluación docente:** en otra carpeta, `git clone` → `dvc pull` →
      `docker compose up` siguiendo **solo** el README → agregar a la bandeja archivos de un periodo
      nuevo (incluidos inválidos y correcciones) → verificar que todo corre sin intervención.
- [ ] `DECISIONES.md` completo (ver lista abajo).
- [ ] Evidencias: capturas de Airflow, `model_comparison.md` y reporte de monitoreo.
- [ ] Dar acceso a los docentes en GitHub y DagsHub (o dejar ambos públicos).
- [ ] `git tag entrega-lab1 && git push origin entrega-lab1`.

**Total estimado: ~10 días de trabajo.**

## Contenido mínimo de `CLAUDE.md`

- Cómo correr las pruebas (`pytest`), el linter y Airflow.
- Reglas: la lógica solo va en `src/reposicion`; los DAGs no contienen lógica; nunca se usa
  `datetime.now()` en la lógica; toda lectura de datos pasa por `asof`; ningún dato ni modelo va a
  git; la bandeja es read-only; las escrituras son atómicas y particionadas; los costos y parámetros
  van en `config/`, nunca hardcodeados.
- Convenciones: ramas `feat/*`, PR a `main`, español en la documentación.

## Lista de decisiones para `DECISIONES.md`

1. Fecha de corte, horizonte y cobertura del pedido.
2. Definición de `fecha_disponible` y la función as-of (alternativas: mtime, fecha de ingesta).
3. Uso de promociones futuras y transacciones con lag.
4. Reglas duras vs. blandas, cuarentena vs. modo degradado y cuándo falla el DAG.
5. Correcciones: publicados inmutables, monitoreo recalculado y re-emisión opcional.
6. Baseline y modelo elegidos; deep learning descartado (costo/beneficio).
7. Esquema de validación temporal y métricas.
8. Newsvendor, cuantil crítico, suma de cuantiles vs. cuantil semanal, y el supuesto de inventario 0.
9. Criterio champion/challenger.
10. DVC + DagsHub, commits de Airflow a la rama `publicaciones` y manejo de credenciales.
11. LocalExecutor, pip+venv, pandera.
