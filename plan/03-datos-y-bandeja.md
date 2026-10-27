# 03 — Datos, bandeja y disponibilidad en el tiempo

Es la parte central del laboratorio: *"la complejidad no está en el modelo, sino en operar el
producto en el tiempo"*.

## Fuentes

| Fuente | Granularidad | Notas conocidas del dataset |
|---|---|---|
| `train` (ventas + onpromotion) | día × tienda × familia | Faltan los 25-dic; hay tiendas que abren tarde (series en 0 al inicio); terremoto 2016-04-16 |
| `transactions` | día × tienda | Llega con huecos; no existe para fechas futuras → solo sirve con lag |
| `oil` | día hábil | Huecos en fines de semana y en algunos días → forward-fill **solo con datos pasados** |
| `holidays_events` | evento | Se conoce por adelantado; `transferred`, `Bridge`, `Additional`, `Work Day`; local/regional/nacional |
| `stores` | maestro | Ciudad, estado, tipo, cluster; cambia muy poco |

## Principio as-of (anti-leakage)

1. **Ledger de ingesta** (`data/ledger/ingest_log.parquet`), con una fila por archivo visto:
   `fuente, fecha_dato, version, sha256, fecha_disponible, fecha_ingesta, estado (ok|rechazado|cuarentena), motivo`.
2. **`fecha_disponible`** es el momento en que el archivo existía en la bandeja, deducido por
   convención del nombre o del layout (por ejemplo `bandeja/<fecha_entrega>/<fuente>_<fecha_dato>.csv`).
   **No se usa el mtime**, que no es confiable ni reproducible.
3. `asof(fuente, T)` devuelve, para cada `fecha_dato`, la **última versión con
   `fecha_disponible ≤ T`**. Todos los features y entrenamientos de un corte T pasan por esta función.
4. Promociones futuras (`onpromotion` del horizonte) **solo** se usan si llegaron antes de T. Si no
   llegaron, el feature va como NaN y LightGBM lo maneja.
5. **Prueba clave:** pronosticar un corte T con la bandeja completa tiene que dar exactamente lo
   mismo que hacerlo con una bandeja truncada en T. Esa prueba de leakage debe estar en CI.

## Simulador de bandeja (`tools/simulate_bandeja.py`)

Genera `bandeja_sim/` desde 2017-01-01 hasta 2017-08-15 a partir de `data/kaggle`, con semilla fija.
Es parametrizable para poder reproducir lo que podría pasar en la evaluación:

| Escenario | Cómo se simula | Comportamiento esperado del producto |
|---|---|---|
| Llegada normal | ventas del día D entregadas en D+1 | Ingesta OK |
| Fuentes con distinta frecuencia | transactions con lag de 2–3 días; oil solo en días hábiles; holidays por trimestre adelantado | No falla; usa lo que hay |
| Archivo que no llega | se omite un día de ventas de alguna fuente | Aviso y continúa; el monitoreo marca "real pendiente" |
| Llegada tardía | archivo de D entregado en D+5 | Se ingesta cuando aparece; dispara reprocesamiento si afecta cortes ya calculados |
| **Corrección** | archivo `v2` de una fecha ya entregada con valores cambiados | Nueva versión en el ledger → reprocesar features y monitoreo; el publicado original no se toca |
| Tienda cerrada | ventas en 0 para toda una tienda en un día | Es negocio esperado: **no** debe fallar |
| Tienda nueva | store_nbr con historia corta | No falla; sus features se apoyan en el cluster/tipo |
| Datos inválidos | columnas faltantes, tipos rotos, ventas negativas, duplicados, store desconocido, fecha fuera de rango | **Cuarentena**: no entra a processed y el DAG marca la falla de calidad sin contaminar el resultado |
| Archivo duplicado idéntico | mismo hash entregado dos veces | Se ignora (idempotencia) |

> Cuando llegue la bandeja oficial: se ajusta `config/sources.yaml` (patrones de nombre y cómo se
> deduce `fecha_disponible`) y, si hace falta, un adaptador en `ingest/`. **Nada más debería cambiar.**

## Validación (pandera + reglas)

**Reglas duras → rechazo/cuarentena del archivo** (no se propaga):
- Esquema: columnas, tipos, fecha parseable.
- Llave única (`date, store_nbr, family`); sin duplicados.
- `sales ≥ 0`, `onpromotion ≥ 0` y enteros.
- `store_nbr` ∈ maestro de tiendas y `family` ∈ catálogo (salvo que la tienda nueva venga en `stores`).
- `fecha_dato` coherente con el nombre del archivo; no hay fechas futuras respecto a la entrega.

**Reglas blandas → advertencia y registro, sin falla:**
- Tienda con todas sus ventas en 0 (cerrada o feriado).
- Petróleo faltante (fin de semana).
- Cambio fuerte de volumen respecto a la mediana de 28 días (se marca para revisión).
- Fuente con retraso dentro de la tolerancia configurada en `sources.yaml`.

**¿Cuándo falla el DAG?** Solo cuando falta algo **imprescindible** para emitir el corte, por ejemplo
si no hay ventas hasta T-1 más allá de la tolerancia. Aun así, primero se intenta degradar: se
pronostica con lo disponible y queda marcado `calidad=degradada` en el manifiesto. El umbral para
fallar va en `validation.yaml`.

## Manejo de correcciones

1. La ingesta detecta un hash distinto para una (`fuente`, `fecha_dato`) ya vista → registra `version+1`.
2. Calcula los **cortes afectados**: todos los T con `fecha_dato` dentro de la ventana de features o
   de evaluación de T.
3. Acciones:
   - **Monitoreo**: se recalculan las métricas de los cortes afectados con el real corregido
     (versión vigente). Esto siempre se hace.
   - **Pronósticos publicados**: **no se reescriben**, porque en su momento se emitieron con la
     información disponible. Si `reemitir_si_corrige: true` en config **y** el corte todavía está
     vigente (su horizonte no ha terminado), se emite una `revision=2` trazable.
4. Todo queda registrado en el ledger y el manifiesto. Esta es una decisión central para
   DECISIONES.md.
