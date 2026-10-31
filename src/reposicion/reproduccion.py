"""Reproducción de un pronóstico publicado.

`reproducir(corte, revision, dir_data, cfgs)` vuelve a calcular el pronóstico y el pedido de una
publicación **sin tocar `data/published`** y compara los sha256 contra su manifiesto. Las entradas
son las mismas: el ledger filtrado a `fecha_entrega <= datos_hasta` (la huella de entradas del
manifiesto) y el modelo registrado (`modelo_id`). En `rev=1` el manifiesto no trae `datos_hasta` y
vale el corte; una revisión se reproduce con el `datos_hasta` de su manifiesto.

El cálculo se hace en un directorio temporal cuyo `published/` está vacío y cuyos demás
subdirectorios (`limpio`, `ledger`, `models`, ...) son enlaces de solo lectura a los reales.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from reposicion import rutas
from reposicion.parametros import Configs
from reposicion.publicacion import ARCHIVOS, directorio_publicacion, pronosticar_corte

log = logging.getLogger(__name__)

# Campos del manifiesto que dependen solo de las entradas, la configuración y el modelo (el
# `git_commit` y los avisos del manifiesto original se informan aparte).
CAMPOS_COMPARABLES = (
    "modelo_id",
    "calidad",
    "advertencias",
    "huella_entradas",
    "sha256_business",
    "sha256_model",
    "filas_pronostico",
    "series",
)


class PublicacionNoEncontrada(FileNotFoundError):
    """No existe `published/corte=T/rev=N/manifest.json`."""


@dataclass
class ResultadoReproduccion:
    corte: date
    revision: int
    datos_hasta: date
    reproducido: bool
    diferencias: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)

    def texto(self) -> str:
        lineas = [f"corte={self.corte} rev={self.revision} (datos_hasta={self.datos_hasta})"]
        lineas += [f"AVISO: {a}" for a in self.avisos]
        if self.reproducido:
            lineas.append("REPRODUCIDO ✓")
        else:
            lineas.append("NO REPRODUCIDO ✗")
            lineas += [f"- {d}" for d in self.diferencias]
        return "\n".join(lineas)


def leer_manifiesto(dir_data: Path, corte: date, revision: int) -> dict:
    ruta = directorio_publicacion(dir_data, corte, revision) / "manifest.json"
    if not ruta.exists():
        raise PublicacionNoEncontrada(f"no existe {ruta}")
    return json.loads(ruta.read_text(encoding="utf-8"))


def commit_actual() -> str | None:
    """Commit del código en uso: `REPOSICION_GIT_COMMIT` (Docker) o `git rev-parse HEAD`."""
    env = os.environ.get("REPOSICION_GIT_COMMIT")
    if env:
        return env
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=rutas.dir_repo(),
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _datos_temporales(dir_data: Path, tmp: Path) -> Path:
    """`tmp/data` con `published/` vacío y enlaces simbólicos al resto de `dir_data`."""
    destino = tmp / "data"
    destino.mkdir()
    for hijo in Path(dir_data).iterdir():
        if hijo.name in ("published", "monitoring"):
            continue
        (destino / hijo.name).symlink_to(hijo.resolve())
    (destino / "published").mkdir()
    return destino


def reproducir(
    corte: date,
    revision: int,
    dir_data: Path,
    cfgs: Configs,
    commit: str | None = None,
) -> ResultadoReproduccion:
    """Recalcula la publicación `corte`/`revision` y compara contra su manifiesto.

    `commit` es el del código en uso (por defecto `git rev-parse HEAD`): si difiere del
    `git_commit` del manifiesto se agrega un aviso con el comando para reproducir exactamente.
    """
    dir_data = Path(dir_data)
    previo = leer_manifiesto(dir_data, corte, revision)
    datos_hasta = date.fromisoformat(previo["datos_hasta"]) if "datos_hasta" in previo else corte
    avisos = []
    actual = commit if commit is not None else commit_actual()
    if actual != previo.get("git_commit"):
        avisos.append(
            f"el commit actual ({actual}) difiere del de la publicación "
            f"({previo.get('git_commit')}); para reproducir exactamente: "
            f"git worktree add ../repro {previo.get('git_commit')} && cd ../repro && dvc pull"
        )

    with tempfile.TemporaryDirectory(prefix="reproducir-") as t:
        tmp = _datos_temporales(dir_data, Path(t))
        nuevo_dir = pronosticar_corte(
            corte,
            tmp,
            cfgs,
            revision,
            datos_hasta=None if "datos_hasta" not in previo else datos_hasta,
            motivo=previo.get("motivo"),
            revision_de=previo.get("revision_de"),
            modelo_id=previo.get("modelo_id"),
        )
        nuevo = json.loads((nuevo_dir / "manifest.json").read_text(encoding="utf-8"))

    diferencias = []
    for archivo in ARCHIVOS:
        a, b = previo["sha256_archivos"][archivo], nuevo["sha256_archivos"][archivo]
        if a != b:
            diferencias.append(f"{archivo}: sha256 publicado {a[:12]}… != recalculado {b[:12]}…")
    for campo in CAMPOS_COMPARABLES:
        if previo.get(campo) != nuevo.get(campo):
            diferencias.append(f"{campo}: publicado {previo.get(campo)!r} != {nuevo.get(campo)!r}")
    return ResultadoReproduccion(corte, revision, datos_hasta, not diferencias, diferencias, avisos)
