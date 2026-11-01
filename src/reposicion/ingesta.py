"""Ingesta de la bandeja: copia a `data/raw`, validación, ledger y almacén limpio.

La bandeja es un sistema externo de solo lectura: nunca se escribe, mueve ni borra nada en ella.
La ingesta es idempotente: la llave es `(archivo relativo, sha256)`; lo ya registrado no se toca.
"""

from __future__ import annotations

import hashlib
import logging
import re
import shutil
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from reposicion.almacen import leer_ledger, limpio_al_dia, reconstruir_limpio, ruta_ledger
from reposicion.fuentes import SIEMPRE_DISPONIBLE, ConfigFuentes
from reposicion.io import escribir_parquet
from reposicion.validacion import (
    ConfigValidacion,
    ResultadoValidacion,
    leer_texto,
    validar_archivo,
)

log = logging.getLogger(__name__)

COLUMNAS_LEDGER = [
    "fuente",
    "fecha_dato",
    "fecha_entrega",
    "archivo",
    "sha256",
    "estado",
    "version",
    "es_correccion",
    "es_tardio",
    "errores",
    "advertencias",
    "filas",
]
ORDEN_LEDGER = ["fecha_entrega", "fuente", "fecha_dato", "archivo"]


@dataclass(frozen=True)
class ArchivoBandeja:
    fuente: str
    fecha_dato: date
    fecha_entrega: date
    ruta: Path  # absoluta, dentro de la bandeja
    relativa: str  # "<fecha_entrega>/<archivo>"
    sha256: str


@dataclass
class ResumenIngesta:
    nuevos: int = 0
    validos: int = 0
    cuarentena: int = 0
    duplicados: int = 0
    conflictos: int = 0  # archivos ya ingeridos cuyo contenido cambió en la bandeja (se ignoran)
    con_advertencias: int = 0
    correcciones: list[str] = field(default_factory=list)
    tardios: list[str] = field(default_factory=list)

    def texto(self) -> str:
        lineas = [
            f"archivos nuevos: {self.nuevos} (válidos {self.validos}, cuarentena "
            f"{self.cuarentena}, duplicados {self.duplicados})",
            f"con advertencias: {self.con_advertencias}",
        ]
        if self.conflictos:
            lineas.append(
                f"conflictos ignorados (archivo modificado en la bandeja): {self.conflictos}"
            )
        lineas += [f"corrección: {c}" for c in self.correcciones]
        lineas += [f"tardío: {t}" for t in self.tardios]
        return "\n".join(lineas)


def _sha256(ruta: Path) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def escanear_bandeja(bandeja: Path, hasta: date, cfg: ConfigFuentes) -> list[ArchivoBandeja]:
    """Archivos de la bandeja con `fecha_entrega <= hasta`, en orden estable.

    Orden: fecha de entrega, `tiendas` primero y luego por nombre. Ignora lo que empieza con el
    prefijo configurado y avisa (warning) de los nombres que no coinciden con el patrón.
    """
    cb = cfg.bandeja
    patron_carpeta = re.compile(cb.patron_carpeta)
    patron_archivo = re.compile(cb.patron_archivo)
    encontrados: list[ArchivoBandeja] = []
    for carpeta in sorted(Path(bandeja).iterdir()):
        if carpeta.name.startswith(cb.prefijo_ignorado):
            continue
        if not carpeta.is_dir() or not patron_carpeta.match(carpeta.name):
            log.warning("bandeja: se ignora %s (no es una carpeta de fecha)", carpeta.name)
            continue
        try:
            entrega = date.fromisoformat(carpeta.name)
        except ValueError:
            log.warning("bandeja: carpeta con fecha inválida %s", carpeta.name)
            continue
        if entrega > hasta:
            continue
        for archivo in sorted(carpeta.iterdir()):
            if archivo.name.startswith(cb.prefijo_ignorado):
                continue
            m = patron_archivo.match(archivo.name)
            if not archivo.is_file() or not m or m["fuente"] not in cfg.fuentes:
                log.warning("bandeja: nombre no reconocido %s/%s", carpeta.name, archivo.name)
                continue
            try:
                fecha_dato = date.fromisoformat(m["fecha_dato"])
            except ValueError:
                log.warning("bandeja: fecha inválida en %s/%s", carpeta.name, archivo.name)
                continue
            encontrados.append(
                ArchivoBandeja(
                    m["fuente"],
                    fecha_dato,
                    entrega,
                    archivo,
                    f"{carpeta.name}/{archivo.name}",
                    _sha256(archivo),
                )
            )
    encontrados.sort(key=lambda a: (a.fecha_entrega, a.fuente != "tiendas", a.relativa))
    return encontrados


def _ledger_vacio() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "fuente": pd.Series(dtype="str"),
            "fecha_dato": pd.Series(dtype="datetime64[ns]"),
            "fecha_entrega": pd.Series(dtype="datetime64[ns]"),
            "archivo": pd.Series(dtype="str"),
            "sha256": pd.Series(dtype="str"),
            "estado": pd.Series(dtype="str"),
            "version": pd.Series(dtype="int64"),
            "es_correccion": pd.Series(dtype="bool"),
            "es_tardio": pd.Series(dtype="bool"),
            "errores": pd.Series(dtype="str"),
            "advertencias": pd.Series(dtype="str"),
            "filas": pd.Series(dtype="int64"),
        }
    )


def _maestros_iniciales(
    dir_data: Path, ledger: pd.DataFrame
) -> list[tuple[date, date, frozenset[int]]]:
    """Snapshots del maestro de tiendas: (fecha_entrega, fecha_dato, tiendas), ordenados."""
    snapshots = [
        (
            SIEMPRE_DISPONIBLE,
            SIEMPRE_DISPONIBLE,
            frozenset(leer_texto(dir_data / "historico" / "tiendas.csv")["store_nbr"].astype(int)),
        )
    ]
    previos = ledger[(ledger["fuente"] == "tiendas") & (ledger["estado"] == "valido")]
    for f in previos.itertuples():
        tiendas = leer_texto(dir_data / "raw" / f.archivo)["store_nbr"].astype(int)
        snapshots.append((f.fecha_entrega.date(), f.fecha_dato.date(), frozenset(tiendas)))
    return sorted(snapshots, key=lambda s: (s[0], s[1]))


def _es_tardio(fcfg, fecha_dato: date, fecha_entrega: date) -> bool:
    """¿Llegó después de su plazo nominal (`fecha_dato + lag_esperado`)?

    Se mide **sin** la tolerancia: un dato que llega dentro de ella no hace fallar nada (modo
    degradado), pero sí puede llegar después de un corte que lo necesitaba, y entonces ese corte
    merece una revisión (ver `revisiones.py`). La tolerancia solo sirve para la calidad de datos.
    """
    if fcfg.lag_esperado_dias is None:
        return False
    return fecha_entrega > fecha_dato + timedelta(days=fcfg.lag_esperado_dias)


def ingestar(
    hasta: date,
    dir_data: Path,
    bandeja: Path,
    cfg_fuentes: ConfigFuentes,
    cfg_validacion: ConfigValidacion,
) -> ResumenIngesta:
    """Ingiere los archivos nuevos de la bandeja con `fecha_entrega <= hasta`."""
    dir_data, bandeja = Path(dir_data), Path(bandeja)
    resumen = ResumenIngesta()
    ledger = leer_ledger(dir_data) if ruta_ledger(dir_data).exists() else _ledger_vacio()
    conocidos = set(zip(ledger["archivo"], ledger["sha256"], strict=True))
    rutas_conocidas = set(ledger["archivo"])

    nuevos: list[ArchivoBandeja] = []
    for a in escanear_bandeja(bandeja, hasta, cfg_fuentes):
        if (a.relativa, a.sha256) in conocidos:
            continue
        if a.relativa in rutas_conocidas:
            log.warning("bandeja: %s cambió después de ingerirse; se ignora", a.relativa)
            resumen.conflictos += 1
            continue
        nuevos.append(a)

    if not nuevos:
        # Un fallo anterior entre escribir el ledger y reconstruir `limpio/` se repara aquí.
        if not limpio_al_dia(dir_data, cfg_fuentes):
            reconstruir_limpio(dir_data, cfg_fuentes)
        return resumen

    familias = set(leer_texto(dir_data / "historico" / "ventas.csv")["family"].unique())
    maestros = _maestros_iniciales(dir_data, ledger)
    # Versión válida vigente por (fuente, fecha_dato): (versión, sha256, filas, entrega), la de
    # mayor fecha de entrega (desempate por versión), igual que `asof`. `ultima_version` lleva la
    # numeración por orden de ingesta, que no depende de cuál sea la vigente.
    vigentes: dict[tuple[str, date], tuple[int, str, int, date]] = {}
    ultima_version: dict[tuple[str, date], int] = {}
    ordenado = ledger[ledger["estado"] == "valido"].sort_values(["fecha_entrega", "version"])
    for f in ordenado.itertuples():
        vigentes[(f.fuente, f.fecha_dato.date())] = (
            int(f.version),
            f.sha256,
            int(f.filas),
            f.fecha_entrega.date(),
        )
    for f in ordenado.itertuples():
        llave = (f.fuente, f.fecha_dato.date())
        ultima_version[llave] = max(ultima_version.get(llave, 0), int(f.version))

    filas_nuevas = []
    for a in nuevos:
        destino = dir_data / "raw" / a.relativa
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(a.ruta, destino)  # la bandeja solo se lee
        fcfg = cfg_fuentes.fuentes[a.fuente]
        vigente = vigentes.get((a.fuente, a.fecha_dato))

        if vigente is not None and vigente[1] == a.sha256:
            estado, version, es_corr, es_tard = "duplicado", vigente[0], False, False
            errores, advertencias, filas = [], [], vigente[2]
            resumen.duplicados += 1
        else:
            res = _validar(destino, a, cfg_fuentes, cfg_validacion, maestros, familias)
            errores, advertencias, filas = res.errores, res.advertencias, res.filas
            if not res.valido:
                estado, version, es_corr, es_tard = "cuarentena", 0, False, False
                resumen.cuarentena += 1
            else:
                estado = "valido"
                version = ultima_version.get((a.fuente, a.fecha_dato), 0) + 1
                es_corr = vigente is not None
                es_tard = vigente is None and _es_tardio(fcfg, a.fecha_dato, a.fecha_entrega)
                ultima_version[(a.fuente, a.fecha_dato)] = version
                # `nuevos` va ordenado por entrega, pero una carpeta antigua que aparece tarde
                # puede traer un archivo anterior al vigente: no lo desplaza.
                if vigente is None or a.fecha_entrega >= vigente[3]:
                    vigentes[(a.fuente, a.fecha_dato)] = (
                        version,
                        a.sha256,
                        filas,
                        a.fecha_entrega,
                    )
                resumen.validos += 1
                etiqueta = f"{a.fuente} {a.fecha_dato} (entrega {a.fecha_entrega})"
                if es_corr:
                    resumen.correcciones.append(etiqueta)
                if es_tard:
                    resumen.tardios.append(etiqueta)
                if a.fuente == "tiendas":
                    nuevos_maestros = frozenset(res.datos["store_nbr"])
                    maestros.append((a.fecha_entrega, a.fecha_dato, nuevos_maestros))
                    maestros.sort(key=lambda s: (s[0], s[1]))
        if advertencias:
            resumen.con_advertencias += 1
        filas_nuevas.append(
            {
                "fuente": a.fuente,
                "fecha_dato": pd.Timestamp(a.fecha_dato),
                "fecha_entrega": pd.Timestamp(a.fecha_entrega),
                "archivo": a.relativa,
                "sha256": a.sha256,
                "estado": estado,
                "version": version,
                "es_correccion": es_corr,
                "es_tardio": es_tard,
                "errores": "; ".join(errores),
                "advertencias": "; ".join(advertencias),
                "filas": filas,
            }
        )
    resumen.nuevos = len(filas_nuevas)

    agregado = pd.concat([ledger, pd.DataFrame(filas_nuevas)], ignore_index=True)[COLUMNAS_LEDGER]
    agregado = agregado.sort_values(ORDEN_LEDGER, kind="stable").reset_index(drop=True)
    escribir_parquet(agregado, ruta_ledger(dir_data))
    reconstruir_limpio(dir_data, cfg_fuentes)
    return resumen


def _validar(
    ruta: Path,
    a: ArchivoBandeja,
    cfg: ConfigFuentes,
    cfg_val: ConfigValidacion,
    maestros: list[tuple[date, date, frozenset[int]]],
    familias: set[str],
) -> ResultadoValidacion:
    try:
        texto = leer_texto(ruta)
    except ValueError as e:
        return ResultadoValidacion(False, errores=[str(e)])
    # Maestro vigente en la fecha de entrega del archivo (nunca el de `hasta`).
    vigentes = [m for m in maestros if m[0] <= a.fecha_entrega]
    tiendas = set(vigentes[-1][2])
    return validar_archivo(
        texto,
        a.fuente,
        a.fecha_dato,
        cfg,
        tiendas,
        familias,
        cfg_val.completitud_min_ventas,
        fecha_entrega=a.fecha_entrega,
        permitir_bajas_tiendas=cfg_val.tiendas_permitir_bajas,
    )
