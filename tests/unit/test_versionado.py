import json
import subprocess
from datetime import date
from pathlib import Path

import pytest

from reposicion import versionado
from reposicion.operacion import cargar_operacion
from reposicion.versionado import ErrorVersionado, publicar_remoto, versionar
from tests.conftest import RAIZ

CORTE = date(2017, 3, 13)


def git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)
    return r.stdout.strip()


@pytest.fixture
def cfg():
    return cargar_operacion(RAIZ / "config" / "operacion.yaml", env={})


@pytest.fixture
def llamadas() -> list[list[str]]:
    return []


@pytest.fixture
def repo(tmp_path, monkeypatch, llamadas) -> Path:
    """Repo git temporal con un commit en `main` y un `data/` con salidas. DVC está simulado."""
    r = tmp_path / "repo"
    (r / "data" / "published" / "corte=2017-03-13").mkdir(parents=True)
    (r / "data" / "published" / "corte=2017-03-13" / "a.parquet").write_bytes(b"datos")
    (r / "data" / "ledger").mkdir()
    (r / "data" / "ledger" / "l.parquet").write_bytes(b"ledger")
    (r / "data" / "vacio").mkdir()
    (r / "codigo.txt").write_text("v1")
    for cmd in (
        ["init", "-b", "main"],
        ["config", "user.name", "dev"],
        ["config", "user.email", "dev@example.com"],
        ["add", "."],
        ["commit", "-m", "inicial"],
    ):
        git(r, *cmd)

    def dvc_falso(args, repo, env=None):
        llamadas.append(args)
        if args[0] == "add":
            for destino in args[1:]:
                p = repo / destino
                contenido = "".join(
                    f"{f.relative_to(p)}:{f.stat().st_size}\n"
                    for f in sorted(p.rglob("*"))
                    if f.is_file()
                )
                (p.parent / f"{p.name}.dvc").write_text(f"outs:\n- path: {p.name}\n{contenido}")
        return ""

    monkeypatch.setattr(versionado, "_dvc", dvc_falso)
    return r


def estado_local(repo: Path) -> tuple[str, str, str]:
    return git(repo, "rev-parse", "HEAD"), git(repo, "status", "--porcelain"), git(repo, "branch")


def test_commit_en_publicaciones_sin_tocar_el_arbol_ni_el_indice(repo, cfg):
    antes = estado_local(repo)
    indice_antes = git(repo, "ls-files", "-s")
    sha = versionar("pronostico", CORTE, repo, cfg, {"manifiestos": {"rev=1": {"a": 1}}})
    assert sha == git(repo, "rev-parse", "refs/heads/publicaciones")
    archivos = git(repo, "ls-tree", "-r", "--name-only", "publicaciones").split("\n")
    assert archivos == [
        "data/ledger.dvc",
        "data/published.dvc",
        "registro/2017-03-13/pronostico.json",
    ]  # el directorio vacío no se versiona
    registro = json.loads(git(repo, "show", "publicaciones:registro/2017-03-13/pronostico.json"))
    assert registro["evento"] == "pronostico" and registro["manifiestos"] == {"rev=1": {"a": 1}}
    # main, su índice y su árbol de trabajo (salvo los .dvc que escribe DVC) no cambian
    assert git(repo, "rev-parse", "HEAD") == antes[0]
    assert git(repo, "ls-files", "-s") == indice_antes
    assert git(repo, "branch").replace("publicaciones", "").split() == antes[2].split()
    sucios = {linea[3:] for linea in git(repo, "status", "--porcelain").splitlines()}
    assert sucios == {"data/ledger.dvc", "data/published.dvc"}


def test_repetir_es_un_noop(repo, cfg):
    primero = versionar("pronostico", CORTE, repo, cfg, {"x": 1})
    assert primero is not None
    assert versionar("pronostico", CORTE, repo, cfg, {"x": 1}) is None
    assert git(repo, "rev-parse", "publicaciones") == primero
    assert git(repo, "rev-list", "--count", "publicaciones") == "1"


def test_autor_y_fecha_del_commit_salen_del_corte(repo, cfg):
    """Sin reloj: autor fijo y fecha = corte, para que el mismo contenido dé el mismo commit."""
    versionar("pronostico", CORTE, repo, cfg, {"x": 1})
    info = git(repo, "log", "-1", "--format=%an|%ae|%aI|%cI|%s", "publicaciones")
    assert info == (
        "motor-reposicion[airflow]|airflow@motor-reposicion.local|"
        "2017-03-13T00:00:00Z|2017-03-13T00:00:00Z|pronostico corte 2017-03-13"
    )


def test_un_evento_nuevo_encadena_commits(repo, cfg):
    a = versionar("pronostico", CORTE, repo, cfg, {"x": 1})
    (repo / "data" / "ledger" / "l.parquet").write_bytes(b"ledger-nuevo-mas-largo")
    b = versionar("seguimiento", CORTE, repo, cfg, {"estado": "pendiente"})
    assert a != b
    assert git(repo, "rev-list", "--count", "publicaciones") == "2"
    assert git(repo, "rev-parse", "publicaciones~1") == a
    archivos = git(repo, "ls-tree", "-r", "--name-only", "publicaciones").split("\n")
    assert "registro/2017-03-13/seguimiento.json" in archivos
    assert "registro/2017-03-13/pronostico.json" in archivos


def test_sin_salidas_solo_deja_el_registro(tmp_path, cfg, monkeypatch):
    r = tmp_path / "vacio"
    r.mkdir()
    git(r, "init", "-b", "main")
    monkeypatch.setattr(versionado, "_dvc", lambda *a, **k: pytest.fail("no debe llamar a DVC"))
    assert versionar("modelo", CORTE, r, cfg, {}) is not None
    assert (
        git(r, "ls-tree", "-r", "--name-only", "publicaciones") == "registro/2017-03-13/modelo.json"
    )


# ------------------------------------------------------------------------- publicar_remoto


def test_sin_credenciales_en_auto_no_falla(repo, cfg, caplog, llamadas):
    res = publicar_remoto(repo, cfg, env={})
    assert res == {"dvc": "sin credenciales", "git": "sin credenciales"}
    assert "GITHUB_TOKEN" in caplog.text and "DAGSHUB_TOKEN" in caplog.text
    assert not llamadas


def test_sin_credenciales_con_siempre_falla(repo, cfg):
    cfg_siempre = cfg.model_copy(update={"push_remoto": "siempre"})
    with pytest.raises(ErrorVersionado, match="DAGSHUB_TOKEN"):
        publicar_remoto(repo, cfg_siempre, env={})


def test_nunca_no_hace_push_aunque_haya_tokens(repo, cfg, llamadas):
    cfg_nunca = cfg.model_copy(update={"push_remoto": "nunca"})
    env = {"DAGSHUB_TOKEN": "x", "GITHUB_TOKEN": "y"}
    assert publicar_remoto(repo, cfg_nunca, env=env) == {"dvc": "omitido", "git": "omitido"}
    assert not llamadas


def test_push_de_dvc_solo_con_su_token(repo, cfg, llamadas):
    """Con tokens: `dvc push` de los .dvc y `git push` de la rama a un remoto local."""
    versionar("pronostico", CORTE, repo, cfg, {"x": 1})
    # Solo hay token de DVC: el push de git (por https, con GITHUB_TOKEN) no se prueba aquí.
    res = publicar_remoto(repo, cfg, env={"DAGSHUB_TOKEN": "token"})
    assert res["dvc"] == "ok" and res["git"] == "sin credenciales"
    assert llamadas[-1][0] == "push"
    assert "data/ledger.dvc" in llamadas[-1]


@pytest.mark.parametrize(
    ("origen", "https"),
    [
        ("git@github.com:ManuelMiranda99/motor-reposicion.git", None),
        ("https://github.com/ManuelMiranda99/motor-reposicion.git", None),
        ("https://usuario:secreto@github.com/ManuelMiranda99/motor-reposicion", "sin-secreto"),
    ],
)
def test_url_https_sin_credenciales(origen, https):
    url = versionado._url_https(origen)
    assert url.startswith("https://github.com/ManuelMiranda99/motor-reposicion")
    assert "secreto" not in url and "@" not in url
