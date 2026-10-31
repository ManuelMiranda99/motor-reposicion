# Fase 8 — Reproducibilidad, documentación y entrega

**Rama:** `feat/docs` · **Estimado:** 1 día · **Prerequisitos:** fases 3 a 7.

El docente va a: clonar el repo, hacer `dvc pull`, levantar Airflow siguiendo **solo** el README y
ejecutar el flujo sobre un periodo no publicado (con situaciones reales de operación). Si
`dvc pull` falla, el proyecto se considera **no reproducible**. Esta fase existe para que eso no
pase.

## Decisiones para el usuario (preguntar al inicio)

1. **Acceso del equipo docente a DagsHub** (DagsHub no permite lectura anónima).
   - (Recommended) Preguntar al usuario si el docente ya confirmó que acepta crear una cuenta y
     usar `tools/dvc_auth.sh`. Si no, recomendarle confirmarlo antes de la fecha límite.
   - Migrar el remoto a un bucket con lectura pública (S3/R2). Es un trabajo extra que requiere
     una cuenta cloud del usuario.
2. **Estado de datos que se entrega en `main`.**
   - (Recommended) Commitear a `main` los `.dvc` de `data/` del final del backfill completo. Así
     `dvc pull` trae el histórico, los modelos, los publicados y el seguimiento, y el docente
     puede reproducir cualquier corte.
   - Entregar solo las entradas (kaggle, histórico, bandeja) y que el docente regenere todo.
3. **Fecha límite y tag.** Pregunta la fecha límite y confirma antes de crear y empujar el tag
   `entrega-lab1` (una acción visible para el docente).

## Tareas

### 1. Reproducir un pronóstico pasado

`python -m reposicion.cli reproducir --corte 2017-03-13 [--rev 1]`:
1. Lee `data/published/corte=T/rev=N/manifest.json`.
2. Avisa si `git rev-parse HEAD` es distinto de `manifest.git_commit` y muestra el comando para
   reproducir exactamente: `git worktree add ../repro <git_commit>` y luego, dentro de ese
   worktree, `dvc pull` y el mismo comando.
3. Recalcula el pronóstico en un directorio temporal, **sin tocar `data/published`**, usando la
   misma huella de entradas: un ledger filtrado a `fecha_entrega <= datos_hasta`. Desde la fase 7,
   `pronosticar_corte` acepta `datos_hasta` (y `revision`): una revisión se reproduce con el
   `datos_hasta` de su manifiesto; en `rev=1` el manifiesto no lo trae y vale el corte.
4. Compara los sha256 contra el manifiesto e imprime `REPRODUCIDO ✓` o las diferencias.

Prueba: `tests/integration/test_reproducir.py`. Agrega al README la sección "Reproducir un
pronóstico publicado", incluyendo cómo obtener el commit correcto desde la rama `publicaciones`
(`git log publicaciones -- registro/<corte>/`).

### 2. Ensayo de la evaluación docente (obligatorio)

En un directorio temporal (el scratchpad), **siguiendo literalmente el README**:

```bash
git clone https://github.com/ManuelMiranda99/motor-reposicion.git ensayo && cd ensayo
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt -e .
./tools/dvc_auth.sh && dvc pull          # el usuario ingresa su token
cp .env.example .env                     # completar
docker compose up -d                     # usa otro puerto o baja el stack del repo principal antes
```

Luego simula el "periodo no publicado": genera con el simulador una bandeja **distinta**, por
ejemplo con otra semilla y escenarios en otras fechas, en una carpeta aparte; apunta `BANDEJA_PATH`
a ella, ajusta `REPOSICION_INICIO` y `REPOSICION_FIN`, despausa los DAGs y verifica que todo corra
sin intervención. Agrega al menos un escenario que no se haya probado antes: dos correcciones
seguidas del mismo día o una fuente que llega con 5 días de retraso.

Anota cada fricción del README y corrígela. Al terminar, `docker compose down -v` del ensayo y
borra el directorio.

Si hay una cuenta de DagsHub distinta a la del usuario, prueba `dvc pull` con ella. Si no la hay,
dilo en el resumen.

### 3. Documentación final

- **`README.md`** completo: qué es el producto, requisitos, instalación desde cero, datos (DVC y
  token), operación (Airflow, DAGs, backfill, cómo usar otra bandeja), CLI, dónde están los
  pronósticos, pedidos y reportes, reproducir un corte, estructura del repo y pruebas.
- **`DECISIONES.md`**: revisa que las decisiones 1–11 estén completas y "Aceptadas", con
  alternativas y justificación. Ponen énfasis especial en la disponibilidad de la información en
  el tiempo, la validación y las correcciones (lo pide el enunciado). Agrega una sección de
  **limitaciones conocidas** (ventas censuradas, inventario 0, backtest con datos revisados,
  suma de cuantiles).
- **`CLAUDE.md`**: actualiza los comandos (Docker, CLI) y las reglas si cambiaron.
- **Evidencias** en `reports/`:
  - `comparacion_modelos.md` (fase 5);
  - `seguimiento.md` (copia del reporte final de la fase 7, con sus PNG): `seguimiento.publicar_reporte_reciente(dir_data, Path("reports"))`
    o `python -m reposicion.cli seguimiento --corte <último> --copiar-reporte` (copia el último
    `data/monitoring/reportes/<corte>.md` a `reports/seguimiento.md` y los PNG como
    `reports/seguimiento_*.png`, con los enlaces reescritos);
  - `evidencia/` (capturas de la UI de Airflow: Grid de los 4 DAGs, un run con cuarentena, un
    run con revisión por corrección);
  - una sección "Evidencias" en el README que enlace todo.

### 4. Estado de datos en `main`

Según la decisión 2: `dvc push` de todo; commitea los `.dvc` de `data/` en esta rama y verifica en
un clon limpio que `dvc pull` trae todo (`dvc status -c` limpio).

### 5. Cierre

1. PR de la fase con CI verde y merge.
2. Revisa la checklist de entregables del enunciado (`plan/06-fases-y-checklist.md` fase 8 y
   `plan/07-riesgos-y-pendientes.md`). Marca lo cumplido y reporta lo que no.
3. Con confirmación del usuario: `git switch main && git pull && git tag -a entrega-lab1 -m "Entrega Laboratorio 1" && git push origin entrega-lab1`.
4. Verifica que el repo de GitHub sea público (o que el docente tenga acceso) y recuérdale al
   usuario que entregue el enlace en el GES.

## Criterios de terminado

- [ ] `reproducir --corte` da `REPRODUCIDO ✓` para al menos 2 cortes, uno de ellos con revisión.
- [ ] El ensayo desde un clon limpio funcionó siguiendo solo el README, con una bandeja nueva.
- [ ] README, DECISIONES y CLAUDE.md están completos; las evidencias están en `reports/`.
- [ ] El tag `entrega-lab1` está en GitHub (con confirmación del usuario).
- [ ] `plan/ESTADO.md` muestra todas las fases ✅.
