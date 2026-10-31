"""Versionado de las salidas operativas desde Airflow (DVC + git con *plumbing*).

El repo está montado en el contenedor y es el mismo árbol de trabajo del desarrollador, y `main`
está protegida: un `git commit` normal ensuciaría su rama. Por eso los registros se confirman con
comandos de bajo nivel de git sobre la rama `publicaciones`, **sin checkout y sin tocar el índice
ni el árbol de trabajo**:

1. `dvc add` de cada directorio de salida de `data/` (deja un `.dvc` por directorio);
2. commit en `refs/heads/publicaciones` con los `.dvc` y `registro/<corte>/<evento>.json`
   (índice temporal con `GIT_INDEX_FILE`; autor, correo y fechas fijos derivados del corte, así el
   mismo contenido da el mismo commit; si el árbol no cambia, no hay commit);
3. `publicar_remoto`: `dvc push` (con `DAGSHUB_TOKEN`) y `git push` de la rama (con
   `GITHUB_TOKEN`), según `push_remoto`. Faltar las credenciales **no** es un error en `auto`.

Nunca se usa el reloj: la fecha del commit sale del corte.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import subprocess
import tempfile
from collections.abc import Mapping
from datetime import date
from pathlib import Path

from reposicion.operacion import ConfigOperacion

log = logging.getLogger(__name__)


class ErrorVersionado(RuntimeError):
    """Falló un comando de git o de DVC."""


def _ejecutar(
    cmd: list[str], repo: Path, env: Mapping[str, str] | None = None, entrada: bytes | None = None
) -> str:
    """Ejecuta un comando en `repo` y devuelve su salida; los errores no exponen credenciales."""
    entorno = {**os.environ, **(env or {})}
    r = subprocess.run(cmd, cwd=repo, env=entorno, input=entrada, capture_output=True)
    if r.returncode != 0:
        detalle = r.stderr.decode("utf-8", "replace").strip()
        detalle = re.sub(r"(x-access-token:)[^@\s]+@", r"\1***@", detalle)
        raise ErrorVersionado(f"{' '.join(cmd[:3])} falló ({r.returncode}): {detalle}")
    return r.stdout.decode("utf-8", "replace").strip()


def _dvc(args: list[str], repo: Path, env: Mapping[str, str] | None = None) -> str:
    """Punto único de llamada a DVC (las pruebas lo reemplazan)."""
    return _ejecutar(["dvc", *args], repo, {"DVC_NO_ANALYTICS": "1", **(env or {})})


def _directorios_a_versionar(dir_data: Path, cfg: ConfigOperacion) -> list[Path]:
    """Directorios de salida que existen y tienen contenido (DVC no versiona carpetas vacías)."""
    salida = []
    for nombre in cfg.directorios_dvc:
        d = dir_data / nombre
        if d.is_dir() and any(d.rglob("*")):
            salida.append(d)
    return salida


def _git(repo: Path, args: list[str], env: Mapping[str, str] | None = None, **kw) -> str:
    return _ejecutar(["git", *args], repo, env, **kw)


def _commit_en_rama(
    repo: Path,
    rama: str,
    archivos: Mapping[str, bytes],
    mensaje: str,
    corte: date,
    cfg: ConfigOperacion,
) -> str | None:
    """Confirma `archivos` (ruta → contenido) sobre `rama` sin tocar índice ni árbol de trabajo."""
    ref = f"refs/heads/{rama}"
    try:
        padre = _git(repo, ["rev-parse", "--verify", "--quiet", ref])
    except ErrorVersionado:
        padre = None
    fecha = f"{corte.isoformat()}T00:00:00+0000"
    ident = {
        "GIT_AUTHOR_NAME": cfg.autor.nombre,
        "GIT_AUTHOR_EMAIL": cfg.autor.correo,
        "GIT_AUTHOR_DATE": fecha,
        "GIT_COMMITTER_NAME": cfg.autor.nombre,
        "GIT_COMMITTER_EMAIL": cfg.autor.correo,
        "GIT_COMMITTER_DATE": fecha,
    }
    with tempfile.TemporaryDirectory() as tmp:
        env = {**ident, "GIT_INDEX_FILE": str(Path(tmp) / "indice")}
        if padre is not None:
            _git(repo, ["read-tree", padre], env)
        for ruta, contenido in sorted(archivos.items()):
            blob = _git(repo, ["hash-object", "-w", "--stdin"], env, entrada=contenido)
            _git(repo, ["update-index", "--add", "--cacheinfo", f"100644,{blob},{ruta}"], env)
        arbol = _git(repo, ["write-tree"], env)
        if padre is not None and arbol == _git(repo, ["rev-parse", f"{padre}^{{tree}}"]):
            return None  # nada cambió: idempotente
        cmd = ["commit-tree", arbol, "-m", mensaje] + (["-p", padre] if padre else [])
        commit = _git(repo, cmd, env)
        _git(repo, ["update-ref", ref, commit, padre or ""], env)
    return commit


def versionar(
    evento: str,
    corte: date,
    repo: Path,
    cfg: ConfigOperacion,
    registro: Mapping[str, object] | None = None,
) -> str | None:
    """`dvc add` de las salidas y commit en la rama de publicaciones. Devuelve el sha o `None`.

    `registro` es el contenido (determinista, sin marcas de tiempo) de
    `registro/<corte>/<evento>.json`.
    """
    repo = Path(repo)
    dir_data = repo / "data"
    destinos = _directorios_a_versionar(dir_data, cfg)
    if not destinos:
        log.warning("versionar(%s, %s): no hay salidas en %s", evento, corte, dir_data)
    else:
        _dvc(["add", *[str(d.relative_to(repo)) for d in destinos]], repo)
    archivos: dict[str, bytes] = {}
    for d in destinos:
        dvc = d.parent / f"{d.name}.dvc"
        archivos[str(dvc.relative_to(repo))] = dvc.read_bytes()
    cuerpo = {"evento": evento, "corte": corte.isoformat(), **(registro or {})}
    archivos[f"registro/{corte.isoformat()}/{evento}.json"] = (
        json.dumps(cuerpo, sort_keys=True, indent=2, ensure_ascii=False, default=str) + "\n"
    ).encode("utf-8")
    commit = _commit_en_rama(
        repo, cfg.rama_publicaciones, archivos, f"{evento} corte {corte.isoformat()}", corte, cfg
    )
    log.info("versionar(%s, %s): %s", evento, corte, commit or "sin cambios (no-op)")
    return commit


def _url_https(origen: str) -> str:
    """Convierte la URL de `origin` (ssh o https) a https sin credenciales."""
    m = re.match(r"(?:git@|ssh://git@)([^:/]+)[:/](.+?)(?:\.git)?/?$", origen)
    if m:
        return f"https://{m.group(1)}/{m.group(2)}.git"
    return re.sub(r"https://[^@/]+@", "https://", origen)


def publicar_remoto(
    repo: Path, cfg: ConfigOperacion, env: Mapping[str, str] | None = None
) -> dict[str, str]:
    """`dvc push` y `git push` de la rama de publicaciones, según `push_remoto`.

    Devuelve el resultado de cada paso (`dvc`, `git`): `ok`, `omitido` o `sin credenciales`.
    En `auto`, la falta de credenciales deja un warning y **no** falla; en `siempre` falla.
    Los errores reales de red o de autorización sí se propagan (la tarea se reintenta).
    """
    repo = Path(repo)
    env = os.environ if env is None else env
    resultado = {"dvc": "omitido", "git": "omitido"}
    if cfg.push_remoto == "nunca":
        log.info("push_remoto=nunca: solo commit local")
        return resultado

    token_dvc = (env.get("DAGSHUB_TOKEN") or env.get("AWS_ACCESS_KEY_ID") or "").strip()
    if token_dvc:
        objetivos = [
            str(d.relative_to(repo)) + ".dvc" for d in _directorios_a_versionar(repo / "data", cfg)
        ]
        _dvc(["push", *objetivos], repo)
        resultado["dvc"] = "ok"
    else:
        _sin_credenciales(cfg, "DAGSHUB_TOKEN", "dvc push")
        resultado["dvc"] = "sin credenciales"

    token_git = (env.get("GITHUB_TOKEN") or "").strip()
    if token_git:
        url = _url_https(_git(repo, ["remote", "get-url", "origin"]))
        cred = base64.b64encode(f"x-access-token:{token_git}".encode()).decode()
        git_env = {  # el token viaja por entorno, no por argv
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "http.extraheader",
            "GIT_CONFIG_VALUE_0": f"Authorization: Basic {cred}",
            "GIT_TERMINAL_PROMPT": "0",
        }
        rama = cfg.rama_publicaciones
        _git(repo, ["push", url, f"refs/heads/{rama}:refs/heads/{rama}"], git_env)
        resultado["git"] = "ok"
    else:
        _sin_credenciales(cfg, "GITHUB_TOKEN", "git push")
        resultado["git"] = "sin credenciales"
    return resultado


def _sin_credenciales(cfg: ConfigOperacion, variable: str, paso: str) -> None:
    if cfg.push_remoto == "siempre":
        raise ErrorVersionado(f"push_remoto=siempre pero falta {variable}: no se puede {paso}")
    log.warning("sin %s: se omite %s (commit local solamente)", variable, paso)
