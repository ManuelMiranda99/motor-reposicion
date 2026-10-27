---
name: lab1-fases
description: Ejecuta, una por una, las fases pendientes del Laboratorio 1 (motor de reposición de inventario con Git + DVC + Airflow 3 sobre datos de Corporación Favorita). Úsala siempre que el usuario pida continuar el laboratorio, "seguir con la siguiente fase", "empecemos la fase N", retomar el plan, implementar ingesta/validación/as-of, features, baseline, LightGBM, backtest, pedido sugerido, DAGs de Airflow, monitoreo, reproducibilidad o la entrega final de este repo, aunque no mencione la palabra "fase".
---

# Laboratorio 1 — ejecución por fases

Este repo es un producto de ML que, cada lunes (fecha de corte), convierte datos de ventas que llegan
por partes en un pronóstico por cuantiles a 14 días y un pedido sugerido por tienda × familia, más el
seguimiento de su desempeño. Lo difícil no es el modelo: es **operar en el tiempo** (datos tardíos,
correcciones, archivos inválidos) de forma **reproducible** e **idempotente**.

Las fases 0 a 2 ya están hechas. Esta skill guía las fases 3 a 8, **una fase por invocación**.

## 1. Orientarse (siempre, antes de tocar código)

1. Lee `plan/ESTADO.md` y toma la **primera fase pendiente** (o la que pida el usuario, si sus
   prerequisitos están hechos).
2. Lee `references/contexto.md`: estado real del repo, contratos ya existentes y trampas conocidas.
3. Lee **solo** la referencia de esa fase:

| Fase | Referencia |
|---|---|
| 3 — Ingesta, ledger, validación, as-of | `references/fase-3-ingesta.md` |
| 4 — Features, baseline, backtest, pedido | `references/fase-4-features-baseline.md` |
| 5 — LightGBM, registro de modelos, publicación offline | `references/fase-5-lgbm.md` |
| 6 — Airflow 3 en Docker Compose | `references/fase-6-airflow.md` |
| 7 — Monitoreo, correcciones, pruebas e2e | `references/fase-7-monitoreo.md` |
| 8 — Reproducibilidad, documentación, entrega | `references/fase-8-entrega.md` |

4. Lee `CLAUDE.md` (reglas del proyecto) y los módulos de `src/reposicion/` de los que dependa la
   fase. Las referencias definen contratos (rutas, columnas, firmas). Si el código real difiere de
   la referencia, **manda el código**: adapta tu implementación y anota la diferencia en el resumen
   final.

## 2. Preparar el entorno

```bash
cd "<raíz del repo>"            # la ruta tiene espacios: cítala siempre entre comillas
git switch main && git pull
source .venv/bin/activate       # pip + venv; nunca instales en el Python global
pip install -r requirements-dev.txt -e .
dvc pull                        # si falla con 401, el usuario debe correr ./tools/dvc_auth.sh
git switch -c <rama de la fase> # ver plan/ESTADO.md
```

## 3. Preguntar las decisiones antes de programar

El usuario pidió explícitamente que se le pregunten **todas las decisiones técnicas** que le
corresponden. Cada referencia de fase tiene una sección "Decisiones para el usuario": hazlas con
`AskUserQuestion` **al inicio**, en español, con la opción recomendada primero y marcada
"(Recommended)", y explica en la descripción el costo y el beneficio de cada una. Agrupa hasta 4
preguntas por llamada. No preguntes lo que ya está decidido (ver `contexto.md` y
`plan/ESTADO.md`). Si durante la implementación aparece otra decisión con impacto real
(arquitectura, contrato de datos, algo que el docente vería), pregunta también; los detalles
menores de implementación los decides tú y los anotas.

Registra cada respuesta en `plan/ESTADO.md` (sección "Decisiones tomadas") y en `DECISIONES.md`
(contexto, alternativas, decisión y justificación).

## 4. Implementar

- **La lógica va en `src/reposicion/`, con pruebas en `tests/`.** Los DAGs y `tools/` solo llaman
  funciones del paquete.
- Sigue el estilo existente (mira `simulador.py`): docstrings y comentarios en español, type hints,
  pydantic para la configuración, `config/*.yaml` para todo parámetro de negocio o de modelo,
  escritura atómica (`tmp` + `os.replace`), determinismo (semillas, orden estable, sin
  `datetime.now()` en la lógica).
- Trabaja en pasos pequeños: módulo → pruebas → `ruff check . && ruff format . && pytest` → sigue.
- Las pruebas unitarias usan datos sintéticos pequeños (ver el fixture de
  `tests/unit/test_simulador.py`); nunca leen `data/` real, porque el CI no tiene esos datos.
- Después de las pruebas, **verifica con los datos reales** (el comando está en cada referencia) y
  revisa que los números tengan sentido (conteos, rangos, tiempos de ejecución).
- Si una dependencia nueva hace falta: `pip install x`, fija la versión que resolvió con `==` en
  `requirements.txt` (runtime) o `requirements-dev.txt` (solo dev/CI).

## 5. Cerrar la fase (checklist)

1. `ruff check . && ruff format --check . && pytest` en verde.
2. Criterios de "terminado" de la referencia de la fase: todos cumplidos (o explicados).
3. Documentación: `DECISIONES.md`, `README.md` (si cambia cómo se usa algo), `plan/ESTADO.md`
   (estado ✅, número de PR y notas) y las casillas de la fase en `plan/06-fases-y-checklist.md`.
4. Si cambiaron datos versionados: `dvc add <ruta>` y luego `dvc push`. Commitea los `.dvc`.
5. Commit con prefijo convencional y estas líneas al final del mensaje:
   `Co-Authored-By: Claude <noreply@anthropic.com>` (usa el modelo que te indique el sistema, si
   te da una línea de atribución propia).
6. `git push -u origin <rama>` y `gh pr create --base main` con secciones `## Resumen` y
   `## Pruebas` (casillas marcadas) y, al final, la línea de atribución que pida el sistema.
7. Espera el CI: `gh run list --branch <rama> --limit 1` y luego
   `gh run watch <id> --exit-status`. Si no aparece ningún run en ~60 s, haz
   `git commit --allow-empty -m "ci: disparar workflow"` y push (ya pasó una vez).
8. CI verde → `gh pr merge <n> --squash --delete-branch`, `git switch main && git pull && git fetch --prune`.
   **No hagas merge con el CI en rojo** y no intentes saltarte la protección de `main`.
9. Responde al usuario **en español**: qué se hizo, qué se verificó (con números), qué quedó
   pendiente o fue distinto a la referencia, y pregunta si sigue con la siguiente fase. No
   arranques la siguiente fase sin confirmación.

## Principios que no se negocian (por qué importan)

- **As-of:** el docente evaluará con un periodo no publicado y juzgará si alguna predicción usó
  información que no existía en la fecha de corte. Toda lectura para features, entrenamiento o
  pronóstico pasa por `reposicion.asof`. La fecha de corte siempre llega como parámetro.
- **La bandeja es read-only:** es un sistema externo; en Docker se monta con `:ro`.
- **Idempotencia:** Airflow reintenta y hace backfill; correr una tarea N veces debe dejar
  exactamente los mismos archivos (mismos hashes).
- **Situación esperada ≠ error:** una tienda cerrada, petróleo faltante en fin de semana o una
  fuente atrasada dentro de la tolerancia no deben tumbar el flujo. Los datos inválidos van a
  cuarentena sin contaminar los resultados.
- **Nada de datos en git:** solo los `.dvc`. `.gitignore` ignora `*.csv` y `*.parquet`; si una
  prueba necesita un CSV fijo, genéralo en `tmp_path`.
- **Publicado = inmutable:** las correcciones generan revisiones, nunca sobrescriben.
