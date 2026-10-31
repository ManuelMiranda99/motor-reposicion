# Motor de Reposición de Inventario

Laboratorio 1 — Product Development (Maestría en Data Science, Universidad Galileo).

Producto de ML que, cada semana (fecha de corte: lunes), transforma los datos de ventas que llegan
diariamente en:

1. un **pronóstico diario a 14 días** por tienda × familia, con cuantiles;
2. un **pedido sugerido** derivado del pronóstico y de los costos de quiebre y de merma
   (`config/business.yaml`);
3. un **reporte de seguimiento** de los pronósticos publicados contra las ventas reales.

Se basa en los datos de Corporación Favorita ([Kaggle — Store Sales](https://www.kaggle.com/competitions/store-sales-time-series-forecasting/data)).

> 🚧 En construcción. Este README se completará con las instrucciones para levantar el producto desde
> cero (DVC + Airflow 3 en Docker Compose).

## Requisitos

- Python 3.11
- Docker + Docker Compose (para Airflow)
- Git y DVC

## Desarrollo local

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt -e .
ruff check . && pytest
```

## Datos (DVC + DagsHub)

Los datos, modelos y pronósticos se versionan con DVC; el remoto es
[DagsHub](https://dagshub.com/ManuelMiranda99/motor-reposicion). Aunque el repositorio es público,
**DagsHub exige iniciar sesión para cualquier descarga**, así que se necesita un token (gratis):

1. Crear una cuenta en [dagshub.com](https://dagshub.com) (se puede entrar con GitHub).
2. Copiar el token en <https://dagshub.com/user/settings/tokens>.
3. Configurarlo y descargar los datos (el token queda solo en `.dvc/config.local`, fuera de git):

```bash
source .venv/bin/activate
./tools/dvc_auth.sh      # pide el token sin mostrarlo en pantalla
dvc pull
```

| Ruta | Contenido |
|---|---|
| `data/kaggle/` | CSV originales de Kaggle (insumo del simulador de bandeja) |
| `data/historico/` | Carga histórica inicial: todo lo entregado hasta 2017-01-01, un CSV por fuente |
| `bandeja_sim/` | Bandeja simulada: `<fecha_entrega>/<fuente>_<fecha_dato>.csv` (2017-01-02 → 2017-09-01) |

### Regenerar la carga histórica y la bandeja simulada

`dvc pull` ya las trae. Para regenerarlas (son deterministas, `config/simulador.yaml`):

```bash
python tools/simulate_bandeja.py --limpiar                     # completa
python tools/simulate_bandeja.py --limpiar --hasta 2017-06-30  # bandeja parcial (luego se puede ampliar)
```

Los escenarios inyectados (faltantes, tardíos, correcciones, duplicados, inválidos) quedan listados
en `bandeja_sim/_escenarios.csv`.

### Ingesta (bandeja → almacén limpio)

```bash
python -m reposicion.cli ingestar --hasta 2017-09-01   # idempotente; repetirlo no cambia nada
```

Copia a `data/raw/` cada archivo nuevo de la bandeja (que es de solo lectura), lo valida y lo
registra en el **ledger** `data/ledger/ingesta.parquet` (hash, versión, estado `valido` /
`cuarentena` / `duplicado`, correcciones y llegadas tardías). Con los válidos reconstruye
`data/limpio/<fuente>.parquet`, que se consulta con `reposicion.asof.asof(fuente, corte, dir_data)`:
exactamente lo que se sabía en la fecha de corte.

### Backtest de un modelo

```bash
python -m reposicion.cli backtest --modelo baseline --corte 2017-08-14
```

Entrena y evalúa con rolling-origin (los últimos 8 lunes cuyos 14 días ya se conocen en el corte;
cada origen entrena con las 52 semanas anteriores) y escribe
`data/backtest/<modelo>/corte=<corte>/predicciones.parquet` y `metricas.parquet` (WAPE, RMSLE,
pinball, cobertura P10–P90 y, sobre el pedido, costo newsvendor, fill rate y % de merma). Los
costos, la cobertura y el lead time del pedido están en `config/business.yaml`; el horizonte, los
cuantiles y la ventana de entrenamiento, en `config/model.yaml`.

### Modelos: entrenar, comparar y pronosticar (fase 5)

LightGBM necesita OpenMP. En macOS: `brew install libomp` (en Docker, `libgomp1`).

```bash
python -m reposicion.cli comparar --corte 2017-08-14    # backtest baseline vs LightGBM → reports/comparacion_modelos.md
python -m reposicion.cli entrenar --corte 2017-01-02    # entrena el challenger y decide si reemplaza al champion
python -m reposicion.cli pronosticar --corte 2017-03-13 # publica data/published/corte=.../rev=1/ (idempotente)
```

- `comparar` hace el backtest de ambos modelos y de la variante "cuantil de la demanda semanal" y
  escribe el reporte (tablas global, por familia y por horizonte, y la decisión de promoción).
- `entrenar` registra el modelo en `data/models/` y en `data/models/registro.parquet`. El criterio
  de reemplazo está en `config/promotion.yaml`. Si no hay champion, el baseline lo es por defecto.
- `pronosticar` usa el champion vigente en el corte (`champion_vigente`), escribe
  `pronostico.parquet`, `pedido.parquet` y `manifest.json` (sin marcas de tiempo) y nunca
  sobrescribe una revisión publicada con otras entradas (`--revision N` para una nueva).

## Estructura

| Ruta | Contenido |
|---|---|
| `src/reposicion/` | Lógica del producto (ingesta, validación, features, modelos, pedido, monitoreo) |
| `dags/` | DAGs de Airflow (solo orquestación) |
| `config/` | Configuración versionada (costos de negocio, modelo, validación) |
| `tests/` | Pruebas (pytest) |
| `tools/` | Utilidades (simulador de bandeja) |
| `plan/` | Plan de trabajo del laboratorio |
| `DECISIONES.md` | Decisiones técnicas y de producto |

## Reproducir un pronóstico publicado

_Pendiente (fase 8)._
