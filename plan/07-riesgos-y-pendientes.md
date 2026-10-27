# 07 — Riesgos y pendientes

## Riesgos

| Riesgo | Impacto | Mitigación |
|---|---|---|
| El formato de la bandeja oficial difiere del simulado | Alto | Un adaptador aislado en `ingest/` + `sources.yaml`; el resto del sistema solo ve el ledger |
| Los docentes no tienen credenciales de push (DagsHub/GitHub) al correr el flujo | Alto | El push es *best effort* (`push_remoto: auto`): pronostica y versiona localmente, y solo advierte si el push falla |
| `dvc pull` falla para los docentes | **Crítico** (proyecto "no reproducible") | Repo de DagsHub público o docentes invitados; probarlo desde un clon limpio y otra cuenta en la fase 8 |
| Commits desde el contenedor chocan con la protección de `main` | Medio | Commits solo a la rama `publicaciones` |
| RAM de Docker insuficiente (Airflow + LightGBM sobre 3M filas) | Medio | LocalExecutor, ventana de entrenamiento desde 2015, dtypes compactos (category/float32), ≥ 6 GB para Docker Desktop |
| Concurrencia en git/DVC durante el backfill | Medio | `max_active_runs=1` + pool `dvc_git` de tamaño 1 |
| Leakage sutil (promos, oil, transactions) | Alto en la nota | Prueba de bandeja truncada vs. completa en CI |
| Los cuantiles se cruzan o la cobertura está mal calibrada | Bajo | Orden monotónico + métrica de cobertura en el criterio de promoción |

## Pendientes / por confirmar con el equipo docente

- [ ] Formato real y layout de la **bandeja** y de la **carga histórica** (nombres, cómo se marca una
      corrección y cómo se deduce la fecha de entrega).
- [ ] Hasta qué fecha llega la carga histórica oficial (puede cambiar la división de la P5).
- [ ] Cómo va a "ejecutar el flujo sobre un periodo no publicado": ¿apuntando `BANDEJA_PATH` a otra
      carpeta? ¿agregando archivos a la misma? El README debe cubrir ambos casos.
- [ ] Fecha límite de entrega (para calendarizar las fases).
- [ ] Si se aceptan las evidencias como imágenes en git o se prefiere otro formato.

## Decisiones que quizá te vuelva a preguntar más adelante

- Valores concretos de los costos de quiebre/merma por grupo de familias (hoy son placeholders
  razonables).
- Si al llegar una corrección se re-emite el pronóstico (`revision=2`) o solo se actualiza el
  monitoreo.
- Si se agrega MLflow para tracking de experimentos o basta con los reportes en DVC.
