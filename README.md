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
