"""Toma las capturas de la UI de Airflow que se entregan como evidencia (reports/evidencia/).

Requiere el stack levantado (`docker compose up -d`) con el historial del backfill y Chromium para
Playwright (una sola vez: `playwright install chromium`).

Uso (desde la raíz del repo, con el .venv activo):

    python tools/capturas_airflow.py                       # las 8 capturas
    python tools/capturas_airflow.py --solo 06_cuarentena  # solo algunas
"""

from __future__ import annotations

import argparse
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

RAIZ = Path(__file__).resolve().parents[1]

# Vista general de los DAGs.
GENERAL = {"01_dags": "/dags"}

# Grid de cada DAG, a todo el ancho y con los últimos 50 runs (el máximo que ofrece la UI).
GRIDS = {
    "02_grid_ingesta_validacion": "ingesta_validacion",
    "03_grid_entrenamiento": "entrenamiento",
    "04_grid_pronostico_semanal": "pronostico_semanal",
    "05_grid_seguimiento_desempeno": "seguimiento_desempeno",
}

# Logs de una tarea en un run concreto: (dag, run_id, tarea).
LOGS = {
    "06_cuarentena": (
        "ingesta_validacion",
        "scheduled__2017-05-11T05:00:00+00:00",
        "reportar_calidad",
    ),
    "07_revision_por_correccion": (
        "seguimiento_desempeno",
        "scheduled__2017-02-13T07:00:00+00:00",
        "emitir_revisiones",
    ),
    "08_corte_degradado": (
        "pronostico_semanal",
        "scheduled__2017-03-13T06:00:00+00:00",
        "verificar_datos",
    ),
}


def _iniciar_sesion(pagina: Page, url: str, usuario: str, clave: str) -> None:
    pagina.goto(f"{url}/auth/login/")
    pagina.fill("#username", usuario)
    pagina.fill("#password", clave)
    pagina.click("input[type=submit]")
    pagina.wait_for_load_state("networkidle")


def _abrir(pagina: Page, url: str, espera_ms: int = 4000) -> None:
    pagina.goto(url)
    pagina.wait_for_load_state("networkidle")
    pagina.wait_for_timeout(espera_ms)


def _capturar_grid(pagina: Page, url: str, dag: str, destino: Path) -> None:
    _abrir(pagina, f"{url}/dags/{dag}", espera_ms=2500)
    colapsar = pagina.locator("button[aria-label='Collapse Details Panel']")
    if colapsar.count():
        colapsar.click()
    pagina.click("button[aria-label='Options']")
    selector = pagina.get_by_text("Number of Dag Runs").locator("xpath=..")
    selector.locator("button, [role=combobox]").first.click()
    pagina.locator("[role=option]").filter(has_text="50").first.click()
    pagina.keyboard.press("Escape")
    pagina.mouse.click(700, 600)
    pagina.wait_for_load_state("networkidle")
    pagina.wait_for_timeout(4000)
    pagina.screenshot(path=destino, full_page=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default="http://localhost:8080")
    parser.add_argument("--usuario", default="airflow")
    parser.add_argument("--clave", default="airflow")
    parser.add_argument("--salida", type=Path, default=RAIZ / "reports" / "evidencia")
    parser.add_argument("--solo", nargs="*", default=[], help="nombres de captura a tomar")
    args = parser.parse_args()

    args.salida.mkdir(parents=True, exist_ok=True)
    quiere = set(args.solo)

    def toca(nombre: str) -> bool:
        return not quiere or nombre in quiere

    with sync_playwright() as p:
        navegador = p.chromium.launch()
        # Las fechas se muestran en UTC, igual que el cron y los run_id.
        contexto = navegador.new_context(
            viewport={"width": 1600, "height": 1000}, timezone_id="UTC"
        )
        pagina = contexto.new_page()
        _iniciar_sesion(pagina, args.url, args.usuario, args.clave)

        for nombre, ruta in GENERAL.items():
            if toca(nombre):
                _abrir(pagina, args.url + ruta)
                pagina.screenshot(path=args.salida / f"{nombre}.png", full_page=True)
                print(nombre)
        for nombre, (dag, run_id, tarea) in LOGS.items():
            if toca(nombre):
                _abrir(pagina, f"{args.url}/dags/{dag}/runs/{run_id}/tasks/{tarea}", espera_ms=5000)
                pagina.screenshot(path=args.salida / f"{nombre}.png", full_page=True)
                print(nombre)
        # Los grids van al final: colapsar el panel de detalles se recuerda en el navegador.
        pagina.set_viewport_size({"width": 1600, "height": 700})
        for nombre, dag in GRIDS.items():
            if toca(nombre):
                _capturar_grid(pagina, args.url, dag, args.salida / f"{nombre}.png")
                print(nombre)

        navegador.close()


if __name__ == "__main__":
    main()
