"""Publicación offline del pronóstico y el pedido de un corte.

```
data/published/corte=<T>/rev=<N>/
    pronostico.parquet  pedido.parquet  manifest.json
```

Las publicaciones son **inmutables** y la ejecución es **idempotente**: repetir `rev=N` con las
mismas entradas, configuración y modelo es un no-op (mismos bytes); con otras entradas lanza
`PublicacionInmutable` y no toca lo publicado. Una revisión (`rev>=2`, ver `revisiones.py`) usa
`datos_hasta`: la fecha hasta la que se leen los datos (as-of), posterior al corte, que sigue
siendo el origen del pronóstico. El manifiesto no lleva marcas de tiempo de reloj.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import subprocess
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from reposicion import rutas
from reposicion.asof import fechas_faltantes, huella_entradas, ultima_fecha_disponible
from reposicion.datos import cargar_datos_asof
from reposicion.entrenamiento import BASELINE, entrenar_modelo
from reposicion.features import construir_features
from reposicion.io import escribir_parquet
from reposicion.modelos.base import cuantiles_requeridos
from reposicion.parametros import Configs
from reposicion.pedido import calcular_pedido
from reposicion.registro import (
    cargar_modelo,
    champion_vigente,
    construir_modelo_id,
    hash_config,
)

log = logging.getLogger(__name__)

ARCHIVOS = ("pronostico.parquet", "pedido.parquet")


class DatosInsuficientes(RuntimeError):
    """No hay ventas suficientemente recientes para pronosticar el corte."""


class PublicacionInmutable(RuntimeError):
    """La revisión ya existe con otras entradas, configuración o modelo: no se sobrescribe."""


class PublicacionInvalida(RuntimeError):
    """El pronóstico no pasó los checks: no se publica."""


def directorio_publicacion(dir_data: Path, corte: date, revision: int) -> Path:
    return Path(dir_data) / "published" / f"corte={corte.isoformat()}" / f"rev={revision}"


def _sha256_archivo(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def _git_commit() -> str:
    """Commit del código: `REPOSICION_GIT_COMMIT` (Docker) o `git rev-parse HEAD`."""
    env = os.environ.get("REPOSICION_GIT_COMMIT")
    if env:
        return env
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=rutas.RAIZ_REPO,
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "desconocido"


def calidad_datos(corte: date, dir_data: Path, cfgs: Configs) -> tuple[str, list[str]]:
    """Chequeo de modo degradado. Lanza `DatosInsuficientes` si no hay ventas recientes."""
    cfg = cfgs.validacion.modo_degradado
    ultima = ultima_fecha_disponible("ventas", corte, dir_data)
    minimo = corte - timedelta(days=1 + cfg.max_dias_sin_ventas)
    if ultima is None or ultima < minimo:
        raise DatosInsuficientes(
            f"las últimas ventas disponibles en el corte {corte} son del {ultima}; se exige al "
            f"menos el {minimo} (max_dias_sin_ventas = {cfg.max_dias_sin_ventas})"
        )
    advertencias: list[str] = []
    huecos = fechas_faltantes(
        "ventas", corte, cfg.ventana_huecos_dias, dir_data, cfg.dias_sin_operacion
    )
    if huecos:
        lista = ", ".join(d.isoformat() for d in huecos)
        advertencias.append(f"ventas: faltan {len(huecos)} fecha(s) en la ventana ({lista})")
    # Fuentes no imprescindibles atrasadas más de su tolerancia: solo advertencia.
    for nombre, f in cfgs.fuentes.fuentes.items():
        if f.imprescindible or f.lag_esperado_dias is None:
            continue
        ult = ultima_fecha_disponible(nombre, corte, dir_data)
        esperada = corte - timedelta(days=f.lag_esperado_dias + f.tolerancia_retraso_dias)
        if ult is None or ult < esperada:
            advertencias.append(f"{nombre}: último dato {ult}, se esperaba al menos el {esperada}")
    return ("degradada" if advertencias else "ok"), advertencias


def _validar(pron: pd.DataFrame, n_series: int, cfgs: Configs, qs: list[str]) -> None:
    """Checks previos a publicar. Lanza `PublicacionInvalida`."""
    h = cfgs.modelo.horizonte_dias
    problemas = []
    if len(pron) != n_series * h:
        problemas.append(f"se esperaban {n_series * h} filas y hay {len(pron)}")
    if pron[qs].isna().to_numpy().any():
        problemas.append("hay NaN en los cuantiles")
    if (pron[qs].to_numpy() < 0).any():
        problemas.append("hay cuantiles negativos")
    if (np.diff(pron[qs].to_numpy(), axis=1) < -1e-9).any():
        problemas.append("hay cuantiles no monótonos")
    if pron.duplicated(["store_nbr", "family", "h"]).any():
        problemas.append("hay filas duplicadas por (serie, h)")
    if sorted(pron["h"].unique()) != list(range(1, h + 1)):
        problemas.append("los horizontes no cubren 1..horizonte")
    if problemas:
        raise PublicacionInvalida("; ".join(problemas))


def pronosticar_corte(
    corte: date,
    dir_data: Path,
    cfgs: Configs,
    revision: int = 1,
    datos_hasta: date | None = None,
    motivo: str | None = None,
    revision_de: int | None = None,
) -> Path:
    """Genera y publica el pronóstico y el pedido de `corte`. Devuelve el directorio `rev=N`.

    `datos_hasta` (opcional, `>= corte`) es la fecha as-of con la que se leen los datos: por
    defecto, el corte. Las features siguen ancladas al origen `corte` (solo usan lo anterior a
    él), pero ven las correcciones entregadas hasta `datos_hasta`. El modelo es el champion
    vigente en `corte`. `motivo` y `revision_de` se anotan en el manifiesto de una revisión.
    """
    dir_data = Path(dir_data)
    if datos_hasta is not None and datos_hasta < corte:
        raise ValueError(f"datos_hasta ({datos_hasta}) es anterior al corte ({corte})")
    visto = corte if datos_hasta is None else datos_hasta
    destino = directorio_publicacion(dir_data, corte, revision)
    calidad, advertencias = calidad_datos(visto, dir_data, cfgs)
    huella = huella_entradas(visto, dir_data)
    sha_negocio, sha_modelo = hash_config(cfgs.negocio), hash_config(cfgs.modelo)

    modelo_id = champion_vigente(corte, dir_data)
    if modelo_id is None:
        # Sin champion registrado: baseline entrenado en el momento, para no fallar.
        modelo_id = construir_modelo_id(
            BASELINE, corte, "sin-registro|" + hash_config(cfgs.modelo, cfgs.negocio), huella
        )
        advertencias.append("sin champion vigente: se entrenó el baseline en el momento")

    # --- inmutabilidad / idempotencia (antes de gastar cómputo)
    if destino.exists():
        previo = json.loads((destino / "manifest.json").read_text(encoding="utf-8"))
        esperado = {
            "huella_entradas": huella,
            "sha256_business": sha_negocio,
            "sha256_model": sha_modelo,
            "modelo_id": modelo_id,
        }
        distintos = [k for k, v in esperado.items() if previo.get(k) != v]
        if distintos:
            raise PublicacionInmutable(
                f"{destino} ya existe y difiere en {distintos}: las publicaciones son inmutables; "
                "emite una revisión nueva"
            )
        log.info("%s ya publicado con las mismas entradas: no-op", destino)
        return destino

    # --- pronóstico
    datos = cargar_datos_asof(visto, dir_data)
    X = construir_features(datos, [corte], cfgs.modelo, cfgs.fuentes, con_objetivo=False)
    if modelo_id.startswith(BASELINE + "-") and champion_vigente(corte, dir_data) is None:
        modelo = entrenar_modelo(BASELINE, corte, dir_data, cfgs, datos)
    else:
        modelo = cargar_modelo(modelo_id, dir_data)
    cuantiles = cuantiles_requeridos(cfgs.modelo, cfgs.negocio)
    q = modelo.predecir_cuantiles(X, cuantiles)
    pron = pd.concat(
        [
            pd.DataFrame(
                {
                    "corte": pd.Timestamp(corte),
                    "store_nbr": X["store_nbr"].astype(int).to_numpy(),
                    "family": X["family"].astype(str).to_numpy(),
                    "fecha_objetivo": X["fecha_objetivo"].to_numpy(),
                    "h": X["h"].astype(int).to_numpy(),
                }
            ),
            q.reset_index(drop=True),
        ],
        axis=1,
    )
    pron["modelo_id"] = modelo_id
    pron = pron.sort_values(["store_nbr", "family", "h"]).reset_index(drop=True)
    n_series = X.groupby(["store_nbr", "family"], observed=True).ngroups
    _validar(pron, n_series, cfgs, list(q.columns))
    pedido = calcular_pedido(pron.drop(columns="modelo_id"), cfgs.negocio)
    if (pedido["pedido"] < 0).any() or pedido["pedido"].isna().any():
        raise PublicacionInvalida("pedido con valores negativos o NaN")
    pedido["modelo_id"] = modelo_id

    # --- escritura atómica del directorio completo
    tmp = destino.with_name(destino.name + ".tmp")
    if tmp.exists():
        shutil.rmtree(tmp)
    escribir_parquet(pron, tmp / "pronostico.parquet")
    escribir_parquet(pedido, tmp / "pedido.parquet")
    manifiesto = {
        "corte": corte.isoformat(),
        "revision": revision,
        "modelo_id": modelo_id,
        "calidad": calidad,
        "advertencias": advertencias,
        "git_commit": _git_commit(),
        "huella_entradas": huella,
        "sha256_business": sha_negocio,
        "sha256_model": sha_modelo,
        "filas_pronostico": len(pron),
        "series": n_series,
        "sha256_archivos": {a: _sha256_archivo(tmp / a) for a in ARCHIVOS},
    }
    if datos_hasta is not None:
        manifiesto.update(
            {
                "datos_hasta": datos_hasta.isoformat(),
                "emitido_en": datos_hasta.isoformat(),
                "revision_de": revision_de,
                "motivo": motivo,
            }
        )
    (tmp / "manifest.json").write_text(
        json.dumps(manifiesto, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, destino)
    log.info("publicado %s (%s, %d series)", destino, calidad, n_series)
    return destino
