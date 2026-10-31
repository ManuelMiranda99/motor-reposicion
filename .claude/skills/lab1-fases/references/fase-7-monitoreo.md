# Fase 7 — Seguimiento del desempeño, correcciones y pruebas end-to-end

**Rama:** `feat/monitoreo` · **Estimado:** 1 día · **Prerequisitos:** fases 3 a 6.

## Objetivo

1. Comparar cada pronóstico publicado con las ventas reales a medida que llegan, con métricas
   técnicas y de negocio, y producir un reporte.
2. Reaccionar a las correcciones: recalcular siempre el seguimiento y, opcionalmente, emitir una
   revisión del pronóstico.
3. Pruebas end-to-end de idempotencia y de no-leakage sobre el pipeline completo (sin Airflow).

## Decisiones para el usuario (preguntar al inicio)

1. **Qué hacer con un pronóstico publicado cuando llega una corrección de datos que lo afecta.**
   - (Recommended) Nunca se reescribe. El seguimiento se recalcula con el dato corregido y, si el
     corte sigue vigente (su horizonte no ha terminado), se emite `rev=N+1` marcada como revisión,
     con `emitido_en` = el corte en que se detectó. `reemitir_si_corrige: true` en config.
   - Solo recalcular el seguimiento, sin revisiones (más simple).
2. **Formato del reporte de seguimiento.**
   - (Recommended) Markdown + gráficos PNG (matplotlib) por corte de evaluación, en
     `data/monitoring/reportes/`, y una copia del más reciente en `reports/seguimiento.md` en la
     fase 8.
   - HTML estático con tablas.
3. **Alertas de degradación del modelo.**
   - (Recommended) Una advertencia en el reporte (y en el log de Airflow) si el WAPE móvil de 4
     cortes supera en más de 20% al del backtest del champion. No dispara el reentrenamiento
     automáticamente.
   - Disparar `entrenamiento` automáticamente al degradarse.

## Módulos y contratos

### `src/reposicion/seguimiento.py`

```python
def evaluar_publicados(corte_eval: date, dir_data: Path, cfgs) -> pd.DataFrame
```

- Para cada publicación `corte=P/rev=N` con `P <= corte_eval`: une el pronóstico con las ventas
  reales de `asof("ventas", corte_eval)` (**siempre la última versión disponible en
  `corte_eval`**, así las correcciones se reflejan solas).
- Por cada (P, rev) calcula: días con real conocido de 14, estado (`completo` / `parcial` /
  `sin_datos`), WAPE, RMSLE, pinball por cuantil, cobertura P10–P90 y costo newsvendor del pedido
  (solo si los 7 días de la cobertura ya tienen real; si no, `pendiente`).
- Desglose por familia y por h.
- Escribe (sobrescribiendo de forma atómica, porque es un recálculo completo y por lo tanto
  idempotente) en `data/monitoring/metricas_por_corte.parquet`,
  `data/monitoring/metricas_por_familia.parquet` y
  `data/monitoring/reportes/<corte_eval>.md` (+ PNGs). Gráficos sugeridos: WAPE y costo por
  corte en el tiempo, y cobertura vs 80%.
- Los días sin real (por ejemplo, el faltante de ventas del 2017-07-04) quedan como
  `real pendiente`. No es error.

### `src/reposicion/revisiones.py`

```python
def emitir_revisiones(corte_eval: date, dir_data, cfgs) -> list[Path]
```

- Usa `correcciones_entre(ledger, corte_eval - 7, corte_eval)` y `cortes_afectados` (fase 3)
  sobre los cortes publicados.
- Para cada P afectado y **todavía vigente** (`corte_eval <= P + horizonte - 1`) y con
  `reemitir_si_corrige`: llama a `pronosticar_corte(P, revision=N+1, datos_hasta=corte_eval)`.
  Para esto, `pronosticar_corte` necesita un parámetro opcional `datos_hasta` (por defecto, el
  corte). Agrégalo con una prueba. El manifiesto de la revisión registra `revision_de`,
  `motivo` y `datos_hasta`.
- Idempotente gracias a la inmutabilidad de `publicacion.py`.

### DAGs

**Estado tras la fase 6:** `dags/seguimiento_desempeno.py` ya tiene `asegurar_ingesta` →
`evaluar_publicados` (stub en `orquestacion.py`) → `versionar_seguimiento` → `publicar_remoto_seguimiento`;
`orquestacion.registro_evento("seguimiento", ...)` devuelve un estado "pendiente" y debe devolver un
resumen determinista del seguimiento (sin timestamps). `data/monitoring` ya está en la lista de
directorios DVC (`config/operacion.yaml`). Una `PublicacionInmutable` en `pronostico_semanal` falla
sin reintento (`AirflowFailException`): las revisiones nuevas las emite `emitir_revisiones`.

Conecta `seguimiento_desempeno`: `asegurar_ingesta` → `emitir_revisiones` →
`evaluar_publicados` → `versionar("seguimiento", corte)`. Quita el stub de la fase 6.

### CLI

`python -m reposicion.cli seguimiento --corte 2017-08-14`

## Pruebas requeridas

**Unitarias:** métricas por corte con datos sintéticos conocidos; estado `parcial` y `pendiente`;
el seguimiento usa la versión corregida; `cortes_afectados` + vigencia → solo los cortes correctos
generan revisión; una revisión nunca toca `rev=1`.

**End-to-end** (`tests/integration/`, marcadas `@pytest.mark.integration`, usando la bandeja
sintética del simulador y el baseline para que sean rápidas, menos de ~1 minuto):

- `test_e2e_idempotente`: corre la secuencia completa de varios cortes (ingesta → pronóstico →
  seguimiento) dos veces en el mismo `dir_data` y compara los sha256 de **todos** los archivos de
  `data/`.
- `test_e2e_backfill_igual_a_operacion`: correr los cortes en orden con la bandeja completa da el
  mismo resultado que correrlos "en vivo" (bandeja ampliada carpeta por carpeta con el simulador
  `--hasta`).
- **`test_e2e_sin_leakage`**: los publicados de un corte T no cambian si la bandeja contiene datos
  posteriores a T.
- `test_e2e_escenarios`: corrección → revisión y seguimiento recalculado; inválido → cuarentena
  sin afectar el pronóstico; tardío → el corte anterior no lo vio y el siguiente sí.

Las pruebas de integración también corren en el CI (son rápidas). Si tardan más de ~2 minutos,
reduce el tamaño de los datos sintéticos, no la cobertura de escenarios.

## Verificación con datos reales (en Airflow)

Backfill de `seguimiento_desempeno` de 2017-01-02 a 2017-08-14. Revisa en el reporte final:
- el corte 2017-02-06 (afectado por la corrección de ventas del 02-03) tiene métricas
  recalculadas, y su revisión existe solo si seguía vigente cuando llegó la corrección (02-10);
- el corte 2017-07-03 muestra el 07-04 como `real pendiente`;
- la cobertura y el WAPE a lo largo del tiempo son razonables.

`dvc add`/`dvc push` (lo hace `versionar`, verifícalo).

## Documentación

- `DECISIONES.md` §7: completar el manejo de correcciones (revisiones, vigencia, `datos_hasta`) y
  las alertas de degradación.
- `README.md`: dónde ver el reporte de seguimiento.

## Criterios de terminado

- [ ] Reporte de seguimiento generado para todos los cortes del backfill.
- [ ] Las pruebas e2e de idempotencia y no-leakage pasan en el CI.
- [ ] Los escenarios de corrección, tardío, faltante e inválido se comportan como dice la tabla de
      `contexto.md`.
- [ ] `plan/ESTADO.md` y DECISIONES actualizados.
