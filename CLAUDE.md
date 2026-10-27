# CLAUDE.md — Reglas del proyecto

Motor de reposición de inventario (Lab 1, Product Development). Transforma datos de ventas que llegan
diariamente en un pronóstico por cuantiles y un pedido sugerido semanal por tienda × familia, y hace
seguimiento del desempeño. Stack: Python 3.11, pip + venv, Git, DVC (remoto DagsHub), Airflow 3 en
Docker Compose, pytest + GitHub Actions. El plan detallado está en `plan/` y el avance en
`plan/ESTADO.md`. Para continuar con la siguiente fase usa la skill `lab1-fases`
(`.claude/skills/lab1-fases/`), que tiene la especificación detallada de las fases 3 a 8.

## Comandos

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt -e .
ruff check . && ruff format --check .   # lint (CI falla si no pasa)
pytest                                  # pruebas
```

## Reglas no negociables

1. **La lógica vive en `src/reposicion/`** y tiene pruebas en `tests/`. Los archivos de `dags/` solo
   orquestan: importan funciones de `reposicion` y les pasan la fecha de corte.
2. **Disponibilidad en el tiempo:** toda predicción se construye solo con la información disponible en
   la fecha de corte. Toda lectura de datos para features, entrenamiento o monitoreo pasa por la
   función as-of. Nunca se usa `datetime.now()` / `date.today()` en la lógica; la fecha de corte
   siempre llega como parámetro (en Airflow: `logical_date` / `data_interval_end`).
3. **La bandeja es un sistema externo de solo lectura.** Nunca se escribe, mueve ni borra nada
   dentro de ella.
4. **Ningún dato ni modelo va a git.** Todo lo que está en `data/` se versiona con DVC. No se
   commitean CSV, Parquet ni modelos.
5. **Idempotencia:** cada tarea escribe en una partición determinista (`corte=YYYY-MM-DD`, y `rev=N` en las publicaciones) con
   escritura atómica (archivo temporal + `os.replace`). Ejecutarla N veces da el mismo resultado que
   ejecutarla una vez. Las semillas son fijas.
6. **Los pronósticos publicados son inmutables.** Una corrección de datos produce una nueva revisión
   y nunca sobrescribe lo publicado.
7. **La configuración va en `config/*.yaml`:** costos de negocio, horizonte, cuantiles, umbrales de
   validación y criterio de reemplazo de modelos. Nunca se hardcodean en el código.
8. **Datos inválidos → cuarentena**, sin contaminar los resultados. **Situaciones esperadas del
   negocio** (tienda cerrada, petróleo faltante en fin de semana, fuente con retraso tolerable) **no
   deben provocar fallas**.

## Convenciones

- Git: `main` está protegida. Se trabaja en ramas `feat/<tema>` o `fix/<tema>`, se integra por PR con
  CI en verde y se hace squash merge. Los commits usan prefijos tipo Conventional Commits (`feat:`,
  `fix:`, `chore:`, `docs:`, `test:`).
- Idioma: documentación, mensajes de commit y docstrings en español; identificadores de código en
  español o inglés, de forma consistente dentro de cada módulo.
- Estilo: ruff (line-length 100). Type hints en las funciones públicas.
- Cada decisión técnica o de producto relevante se registra en `DECISIONES.md` con sus alternativas y
  su justificación.
- Dependencias nuevas: se agregan con versión fijada (`==`) a `requirements.txt` (runtime) o a
  `requirements-dev.txt` (desarrollo).
