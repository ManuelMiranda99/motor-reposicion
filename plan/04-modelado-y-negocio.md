# 04 — Modelado, pedido y criterio de reemplazo

## Objetivo del pronóstico

- Unidad: `store_nbr × family × fecha`, con 1,782 series.
- Fecha de corte T (lunes): se conocen las ventas hasta T-1 (o hasta donde hayan llegado).
- Horizonte h = 1…14 → fechas T…T+13.
- Salida: `q10, q50, q90, q_crit` por fila, más la media si se quiere.

## Baseline (piso de comparación)

**Naive estacional por día de semana:** media de los últimos 4 mismos días de la semana. Cuantiles
empíricos a partir de los residuos históricos de cada serie y cada h. Es simple, robusto y difícil de
superar en series ralas.

## Modelo ML: LightGBM global por cuantiles

- **Estrategia multi-horizonte:** un modelo **directo** con `h` como feature. Así no hay recursión:
  todos los lags se calculan respecto a T (`lag_k` con k ≥ h implícito al anclar en T), lo que evita
  leakage y es fácil de auditar.
- **Target:** `log1p(sales)`. Se entrena un modelo por cuantil (`objective=quantile, alpha=q`) y al
  final se ordenan los cuantiles para que no se crucen.
- **Features**, todas calculadas con `asof(T)`:
  - Ventas anclas: últimas 1, 7, 14, 28, 56 y 364 días (con T como ancla); medias/medianas móviles
    7/14/28/56; mismo día de la semana promedio de 4/8 semanas; proporción de días en cero.
  - Calendario del día objetivo: día de semana, día del mes, mes, quincena/día de pago (los días 15 y
    último del mes son relevantes en Ecuador), semana del año.
  - Feriados del día objetivo: nacional/regional/local según la tienda, transferido, puente, días a
    y desde el feriado.
  - Promociones: `onpromotion` del día objetivo **si llegó antes de T**, y la historia reciente de
    promociones.
  - Petróleo: último valor conocido a T-1 y su tendencia de 28 días, iguales para todo el horizonte.
  - Transacciones: media de 28 días hasta el último dato disponible (con lag).
  - Estáticas: tienda, familia, ciudad, estado, tipo y cluster como categóricas.
- Series con historia insuficiente (tienda nueva) → el modelo global usa las categóricas; si una
  serie tiene 0 ventas en los últimos 56 días, se pronostica 0 (regla documentada).
- **Deep learning: no se usa.** En DECISIONES.md se justifica por costo y beneficio: el entrenamiento
  en CPU dentro de Airflow es caro, hay más riesgo operativo y en la literatura de Favorita/M5 los
  GBDT dominan a ese costo.

## Validación temporal (igual para todos los modelos)

- **Rolling-origin backtest:** 8 cortes semanales (lunes) previos a la fecha de entrenamiento, con
  horizonte de 14 días y reentrenamiento en cada origen con datos `asof(origen)`.
- Ventana de entrenamiento: expanding desde 2015-01-01 (configurable) para acotar tiempo y memoria.
- Se aplican los mismos orígenes y las mismas métricas a baseline y LightGBM. Resultado en
  `reports/model_comparison.{parquet,md}`.

## Métricas

| Tipo | Métrica | Uso |
|---|---|---|
| Técnica (punto) | **WAPE** sobre q50 | principal, interpretable |
| Técnica (punto) | RMSLE | comparable con Kaggle |
| Técnica (probabilística) | **Pinball loss** promedio (q10/q50/q90) | calidad de la incertidumbre |
| Técnica (calibración) | Cobertura del intervalo P10–P90 (ideal ≈ 80%) | ¿los cuantiles son honestos? |
| **Negocio** | **Costo newsvendor** = Σ `c_quiebre·max(y−pedido,0) + c_merma·max(pedido−y,0)` | lo que le importa a operaciones |
| Negocio | Fill rate y % de unidades en merma | fáciles de explicar |

Todo se reporta global, por familia y por h.

## Pedido sugerido (newsvendor)

`config/business.yaml` (ejemplo):

```yaml
cobertura_dias: 7          # el pedido cubre una semana
lead_time_dias: 0
inventario_inicial: 0      # sin datos de inventario (supuesto)
redondeo: entero_arriba
costos:                    # por unidad
  default:     {quiebre: 1.0, merma: 0.5}
  perecederos: {quiebre: 1.0, merma: 1.5}   # PRODUCE, DAIRY, MEATS, POULTRY, SEAFOOD, BREAD/BAKERY, DELI, EGGS
  no_perecederos: {quiebre: 1.0, merma: 0.1}
familias_por_grupo: { ... }
```

- **Cuantil crítico** `τ = c_quiebre / (c_quiebre + c_merma)`. Cada grupo tiene su τ y se entrena
  (o interpola) ese cuantil.
- **Pedido** = `max(0, Σ_{d∈cobertura} q_τ(d) − inventario_inicial)`.
  - Supuesto: sumar cuantiles diarios equivale a asumir dependencia perfecta entre días, lo cual es
    conservador. **Alternativa por evaluar:** entrenar directamente el cuantil τ de la **demanda
    semanal agregada**, que es más correcta. Primero se implementa la versión simple y se compara en
    el backtest con la métrica de negocio. Queda en DECISIONES.md.
- Si cambian los costos en el YAML, cambia τ y cambia el pedido sin tocar código. Habrá una prueba
  explícita de esto.
- Si se agrega un cuantil que no tiene modelo entrenado, se interpola linealmente entre los cuantiles
  disponibles y se registra un aviso.

## Criterio de reemplazo (champion / challenger) — `config/promotion.yaml`

Un challenger reemplaza al champion vigente **solo si**, en el mismo backtest (mismos orígenes y la
misma ventana más reciente):

1. el **costo de negocio** total es al menos **3% menor**;
2. el **WAPE** no empeora más de 1%;
3. la cobertura P10–P90 está en [70%, 90%];
4. ninguna familia con más del 5% del volumen empeora su costo en más de 10%;
5. pasa los checks técnicos: predicciones no negativas, sin NaN y con 1,782 series × 14 días.

Si no cumple, sigue el champion y se registra el motivo. El registro guarda la versión del modelo,
el hash DVC, las métricas y la fecha. Mientras no exista un modelo entrenado, el champion inicial es
el baseline.

## Reentrenamiento

- DAG `train_evaluate` mensual (primer lunes) o manual: entrena el challenger con `asof(T)`, corre el
  backtest, aplica el criterio y promueve o no.
- El DAG semanal de pronóstico **solo** usa el champion vigente. No entrena, lo que lo hace rápido y
  determinista.
