"""Seguimiento del desempeño: compara lo publicado con las ventas reales que ya llegaron.

`evaluar_publicados(corte_eval, ...)` es un **recálculo completo** y determinista as-of
`corte_eval`: para cada publicación `corte=P/rev=N` con `P <= corte_eval` (y, si es una revisión,
`emitido_en <= corte_eval`) une el pronóstico con `asof("ventas", corte_eval)`, la última versión
de cada día visible en esa fecha, así que las correcciones de datos se reflejan solas. Los días sin
real (aún no ocurren, o faltan como el 2017-07-04) quedan como "real pendiente": no es un error.

Salidas, en la partición del corte de evaluación (se reescriben de forma atómica; repetir el
cálculo da los mismos bytes):

```
data/monitoring/corte=<corte_eval>/metricas_por_corte.parquet    una fila por (corte, revisión)
data/monitoring/corte=<corte_eval>/metricas_por_familia.parquet  … × familia
data/monitoring/corte=<corte_eval>/metricas_por_h.parquet        … × horizonte h
data/monitoring/corte=<corte_eval>/resumen.json                  lo que va al registro de git
data/monitoring/reportes/<corte_eval>.md  (+ PNG)                reporte legible
```

Alerta de degradación (solo advertencia): WAPE móvil agrupado de los últimos `ventana_cortes`
cortes publicados contra el WAPE del backtest del champion vigente.
"""

from __future__ import annotations

import io
import json
import logging
import os
import re
import shutil
from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # sin pantalla (Airflow, CI)

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from reposicion.almacen import leer_parquet  # noqa: E402
from reposicion.asof import asof  # noqa: E402
from reposicion.io import escribir_parquet  # noqa: E402
from reposicion.metricas import metricas_pedido, metricas_tecnicas  # noqa: E402
from reposicion.parametros import Configs  # noqa: E402
from reposicion.publicacion import cortes_con_publicacion, revisiones_publicadas  # noqa: E402
from reposicion.registro import champion_vigente, leer_registro  # noqa: E402

log = logging.getLogger(__name__)

COBERTURA_NOMINAL = 0.80  # P10–P90
COLS_FAMILIA = ["corte", "revision", "family"]  # llaves; sin filas con real quedan vacías
COLS_H = ["corte", "revision", "h"]


def dir_monitoreo(dir_data: Path, corte_eval: date) -> Path:
    return Path(dir_data) / "monitoring" / f"corte={corte_eval.isoformat()}"


def dir_reportes(dir_data: Path) -> Path:
    return Path(dir_data) / "monitoring" / "reportes"


# --------------------------------------------------------------------------------------------
# Publicaciones visibles
# --------------------------------------------------------------------------------------------


def listar_publicaciones(dir_data: Path, corte_eval: date) -> list[dict]:
    """Publicaciones `(corte, revisión)` visibles en `corte_eval`, con su manifiesto.

    Una publicación es visible si `corte <= corte_eval` y fue emitida a más tardar ese día
    (`emitido_en`; el `rev=1` se emite en su corte). Así, evaluar un corte antiguo no cambia si
    después se emitieron revisiones.
    """
    filas = []
    manifiestos = [
        ruta / "manifest.json"
        for corte in cortes_con_publicacion(dir_data)
        for ruta in revisiones_publicadas(dir_data, corte).values()
    ]
    for m in manifiestos:
        manifiesto = json.loads(m.read_text(encoding="utf-8"))
        corte = date.fromisoformat(manifiesto["corte"])
        emitido = date.fromisoformat(manifiesto.get("emitido_en", manifiesto["corte"]))
        if corte <= corte_eval and emitido <= corte_eval:
            filas.append(
                {
                    "corte": corte,
                    "revision": int(manifiesto["revision"]),
                    "ruta": m.parent,
                    "manifiesto": manifiesto,
                    "emitido_en": emitido,
                }
            )
    return sorted(filas, key=lambda f: (f["corte"], f["revision"]))


# --------------------------------------------------------------------------------------------
# Métricas de una publicación
# --------------------------------------------------------------------------------------------


def _agregados(g: pd.DataFrame, qs: list[str]) -> dict[str, float]:
    """Métricas técnicas de las filas con real conocido, más sumas para agrupar después."""
    if g.empty:
        vacio = {"filas_con_real": 0, "abs_err": 0.0, "suma_y": 0.0, "sesgo": np.nan}
        vacio.update({"wape": np.nan, "rmsle": np.nan, "cobertura_p10_p90": np.nan})
        return vacio
    m = metricas_tecnicas(g, qs)
    m.pop("n")
    y, pred = g["y"].to_numpy(np.float64), g["q0.50"].to_numpy(np.float64)
    m.update(
        {
            "filas_con_real": len(g),
            "abs_err": float(np.abs(y - pred).sum()),
            "suma_y": float(y.sum()),
            "sesgo": float(pred.sum() / y.sum() - 1) if y.sum() > 0 else np.nan,
        }
    )
    return m


def _evaluar_publicacion(
    pub: dict, reales: pd.DataFrame, fechas_con_real: set, corte_eval: date, cfgs: Configs
) -> tuple[dict, list[dict], list[dict]]:
    """Fila por corte, filas por familia y filas por h de una publicación."""
    ruta: Path = pub["ruta"]
    pron = leer_parquet(ruta / "pronostico.parquet")
    pron["store_nbr"] = pron["store_nbr"].astype(int)
    pron["family"] = pron["family"].astype(str)
    qs = [c for c in pron.columns if c.startswith("q") and c[1:2].isdigit()]
    unido = pron.merge(
        reales,
        left_on=["fecha_objetivo", "store_nbr", "family"],
        right_on=["fecha_dato", "store_nbr", "family"],
        how="left",
    ).rename(columns={"sales": "y"})
    conocido = unido.dropna(subset=["y"])

    fechas = sorted(pron["fecha_objetivo"].unique())
    con_real = [f for f in fechas if f in fechas_con_real]
    sin_real = [
        f.date().isoformat()
        for f in fechas
        if f not in fechas_con_real and f.date() < corte_eval  # ya debieron llegar
    ]
    pendientes_futuros = [f for f in fechas if f.date() >= corte_eval]
    estado = (
        "sin_datos" if not con_real else "completo" if len(con_real) == len(fechas) else "parcial"
    )

    # --- pedido: el costo exige real en los días de cobertura
    ped = leer_parquet(ruta / "pedido.parquet")
    ped["store_nbr"] = ped["store_nbr"].astype(int)
    ped["family"] = ped["family"].astype(str)
    desde, hasta = ped["cobertura_desde"].iloc[0], ped["cobertura_hasta"].iloc[0]
    dias_cobertura = pd.date_range(desde, hasta)
    cobertura_completa = all(d in fechas_con_real for d in dias_cobertura)
    if cobertura_completa:
        dentro = conocido[
            (conocido["fecha_objetivo"] >= desde) & (conocido["fecha_objetivo"] <= hasta)
        ]
        y_cob = dentro.groupby(["store_nbr", "family"], observed=True).agg(
            y_cobertura=("y", "sum"), n=("y", "size")
        )
        y_cob = y_cob[y_cob["n"] == len(dias_cobertura)].drop(columns="n").reset_index()
        ped = ped.merge(y_cob, on=["store_nbr", "family"], how="left")
    else:
        ped["y_cobertura"] = np.nan

    def negocio(p: pd.DataFrame) -> dict[str, float]:
        m = metricas_pedido(p, cfgs.negocio)
        return {k: v for k, v in m.items()} if cobertura_completa else dict.fromkeys(m, np.nan)

    base = {"corte": pd.Timestamp(pub["corte"]), "revision": pub["revision"]}
    fila = {
        **base,
        "modelo_id": pub["manifiesto"]["modelo_id"],
        "calidad": pub["manifiesto"]["calidad"],
        "emitido_en": pd.Timestamp(pub["emitido_en"]),
        "dias_con_real": len(con_real),
        "estado": estado,
        "dias_sin_real": ";".join(sin_real),
        "dias_futuros": len(pendientes_futuros),
        **_agregados(conocido, qs),
        "costo_estado": "completo" if cobertura_completa else "pendiente",
        **negocio(ped),
    }
    for c in qs:  # pinball ya viene en `_agregados`; se garantiza la columna aunque no haya real
        fila.setdefault(f"pinball_{c}", np.nan)

    familias = []
    for fam, g in conocido.groupby("family", observed=True):
        f = {**base, "family": fam, **_agregados(g, qs)}
        f = {k: v for k, v in f.items() if not k.startswith("pinball_")}
        familias.append(f | {"costo_total": negocio(ped[ped["family"] == fam])["costo_total"]})
    horizontes = []
    for h, g in conocido.groupby("h"):
        f = {**base, "h": int(h), **_agregados(g, qs)}
        horizontes.append({k: v for k, v in f.items() if not k.startswith("pinball_")})
    return fila, familias, horizontes


# --------------------------------------------------------------------------------------------
# Alerta de degradación
# --------------------------------------------------------------------------------------------


def ventana_alerta(por_corte: pd.DataFrame, cfgs: Configs) -> pd.DataFrame:
    """Filas (última revisión de cada corte) que entran a la ventana móvil de la alerta."""
    cfg = cfgs.monitoreo.alerta
    if por_corte.empty:
        return por_corte
    ultima = por_corte.sort_values(["corte", "revision"]).groupby("corte").tail(1)
    ok = ultima[ultima["dias_con_real"] >= cfg.min_dias_con_real]
    return ok.sort_values("corte").tail(cfg.ventana_cortes)


def evaluar_alerta(
    por_corte: pd.DataFrame, corte_eval: date, dir_data: Path, cfgs: Configs
) -> dict:
    """WAPE móvil agrupado vs WAPE del backtest del champion vigente. Solo advierte."""
    cfg = cfgs.monitoreo.alerta
    v = ventana_alerta(por_corte, cfgs)
    resultado: dict = {
        "estado": "insuficiente",
        "alerta": False,
        "ventana_cortes": cfg.ventana_cortes,
        "umbral_degradacion": cfg.umbral_degradacion,
        "cortes_en_ventana": [c.date().isoformat() for c in v["corte"]] if len(v) else [],
        "wape_movil": None,
        "wape_referencia": None,
        "modelo_referencia": None,
        "mensaje": f"menos de {cfg.ventana_cortes} cortes con real suficiente: sin alerta",
    }
    if len(v) < cfg.ventana_cortes or v["suma_y"].sum() <= 0:
        return resultado
    movil = float(v["abs_err"].sum() / v["suma_y"].sum())
    resultado["wape_movil"] = round(movil, 6)
    modelo_id = champion_vigente(corte_eval, dir_data)
    referencia = None
    if modelo_id is not None:
        reg = leer_registro(dir_data)
        fila = reg[reg["modelo_id"] == modelo_id]
        if len(fila) and pd.notna(fila.iloc[0]["wape"]):
            referencia = float(fila.iloc[0]["wape"])
    resultado["modelo_referencia"] = modelo_id
    if referencia is None:
        resultado.update(estado="sin_referencia", mensaje="sin WAPE de backtest del champion")
        return resultado
    resultado["wape_referencia"] = round(referencia, 6)
    exceso = movil / referencia - 1
    resultado["exceso_relativo"] = round(exceso, 6)
    if exceso > cfg.umbral_degradacion:
        resultado.update(
            estado="degradacion",
            alerta=True,
            mensaje=(
                f"ADVERTENCIA: el WAPE móvil de {cfg.ventana_cortes} cortes ({movil:.4f}) supera "
                f"en {exceso:.1%} al del backtest del champion ({referencia:.4f}); umbral "
                f"{cfg.umbral_degradacion:.0%}. No se reentrena automáticamente: revisa el modelo."
            ),
        )
        log.warning(resultado["mensaje"])
    else:
        resultado.update(
            estado="ok",
            mensaje=(
                f"WAPE móvil {movil:.4f} vs backtest {referencia:.4f} ({exceso:+.1%}): dentro "
                f"del umbral de {cfg.umbral_degradacion:.0%}"
            ),
        )
    return resultado


# --------------------------------------------------------------------------------------------
# Reporte
# --------------------------------------------------------------------------------------------


def _escribir_atomico(ruta: Path, contenido: bytes) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_name(ruta.name + ".tmp")
    tmp.write_bytes(contenido)
    os.replace(tmp, ruta)


def _guardar_figura(fig: plt.Figure, ruta: Path) -> None:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, metadata={"Software": None})
    plt.close(fig)
    _escribir_atomico(ruta, buf.getvalue())


def _graficos(
    ultima: pd.DataFrame, familias: pd.DataFrame, alerta: dict, base: Path
) -> list[tuple[str, Path]]:
    """PNG del reporte: WAPE y costo por corte, cobertura vs 80% y WAPE móvil por familia."""
    azul, rojo, gris = "#2a6fb0", "#c0392b", "#8a8a8a"
    salida = []
    con_real = ultima[ultima["filas_con_real"] > 0]
    if len(con_real):
        x = con_real["corte"].dt.strftime("%m-%d")
        fig, (a1, a2) = plt.subplots(2, 1, figsize=(9, 6), sharex=True)
        a1.plot(x, con_real["wape"], marker="o", color=azul, label="WAPE por corte")
        if alerta.get("wape_referencia"):
            ref = alerta["wape_referencia"]
            a1.axhline(ref, color=gris, linestyle="--", label=f"backtest champion ({ref:.3f})")
            lim = ref * (1 + alerta["umbral_degradacion"])
            a1.axhline(lim, color=rojo, linestyle=":", label=f"umbral de alerta ({lim:.3f})")
        a1.set_ylabel("WAPE")
        a1.set_title("WAPE por corte publicado (con los reales disponibles)")
        a1.legend(loc="upper left", fontsize=8)
        completos = con_real[con_real["costo_estado"] == "completo"]
        a2.bar(completos["corte"].dt.strftime("%m-%d"), completos["costo_total"] / 1e6, color=azul)
        a2.set_ylabel("Costo newsvendor (millones)")
        a2.set_title("Costo de negocio del pedido (solo con los 7 días de cobertura conocidos)")
        a2.set_xlabel("Corte (mes-día)")
        for a in (a1, a2):
            a.tick_params(axis="x", rotation=60, labelsize=8)
            a.grid(axis="y", alpha=0.3)
        fig.tight_layout()
        ruta = base.with_name(base.name + "_wape_costo.png")
        _guardar_figura(fig, ruta)
        salida.append(("WAPE y costo por corte", ruta))

        fig, ax = plt.subplots(figsize=(9, 3.6))
        ax.plot(x, con_real["cobertura_p10_p90"], marker="o", color=azul, label="cobertura P10–P90")
        ax.axhline(COBERTURA_NOMINAL, color=gris, linestyle="--", label="nominal 80%")
        ax.set_ylim(0, 1)
        ax.set_ylabel("Cobertura")
        ax.set_xlabel("Corte (mes-día)")
        ax.set_title("Cobertura empírica del intervalo P10–P90")
        ax.tick_params(axis="x", rotation=60, labelsize=8)
        ax.legend(fontsize=8)
        ax.grid(axis="y", alpha=0.3)
        fig.tight_layout()
        ruta = base.with_name(base.name + "_cobertura.png")
        _guardar_figura(fig, ruta)
        salida.append(("Cobertura vs 80%", ruta))
    if len(familias):
        fig, ax = plt.subplots(figsize=(8, 7))
        f = familias.sort_values("wape", ascending=True)
        ax.barh(f["family"], f["wape"], color=azul)
        ax.set_xlabel("WAPE agrupado de la ventana")
        ax.set_title("WAPE por familia (cortes de la ventana móvil)")
        ax.tick_params(axis="y", labelsize=7)
        ax.grid(axis="x", alpha=0.3)
        fig.tight_layout()
        ruta = base.with_name(base.name + "_familias.png")
        _guardar_figura(fig, ruta)
        salida.append(("WAPE por familia", ruta))
    return salida


def _fmt(v, formato: str = ".4f") -> str:
    return "—" if v is None or pd.isna(v) else format(v, formato)


def _tabla(df: pd.DataFrame, columnas: list[tuple[str, str, str]]) -> str:
    """Tabla Markdown. `columnas` = (columna, encabezado, formato; "" = texto)."""
    cab = "| " + " | ".join(h for _, h, _ in columnas) + " |"
    sep = "|" + "|".join("---" for _ in columnas) + "|"
    filas = []
    for r in df.itertuples(index=False):
        d = r._asdict()
        celdas = []
        for c, _, f in columnas:
            v = d[c]
            celdas.append(_fmt(v, f) if f else ("—" if v is None or v == "" else str(v)))
        filas.append("| " + " | ".join(celdas) + " |")
    return "\n".join([cab, sep, *filas])


def _familias_ventana(por_familia: pd.DataFrame, ventana: pd.DataFrame) -> pd.DataFrame:
    """WAPE agrupado y costo por familia sobre los cortes (última revisión) de la ventana."""
    if por_familia.empty or ventana.empty:
        return pd.DataFrame(columns=["family", "wape", "costo_total", "suma_y"])
    llaves = ventana[["corte", "revision"]]
    f = por_familia.merge(llaves, on=["corte", "revision"])
    g = f.groupby("family").agg(
        abs_err=("abs_err", "sum"), suma_y=("suma_y", "sum"), costo_total=("costo_total", "sum")
    )
    g["wape"] = g["abs_err"] / g["suma_y"].where(g["suma_y"] > 0)
    return g.reset_index().sort_values("wape", ascending=False)


def _reporte_md(
    corte_eval: date,
    por_corte: pd.DataFrame,
    ultima: pd.DataFrame,
    familias: pd.DataFrame,
    alerta: dict,
    graficos: list[tuple[str, Path]],
) -> str:
    L = [f"# Seguimiento del desempeño — corte de evaluación {corte_eval.isoformat()}", ""]
    L += [
        "Compara cada pronóstico publicado con las ventas reales visibles en la fecha de "
        "evaluación (la última versión de cada día, así que las correcciones ya están "
        "incluidas). Un día sin real es *real pendiente*, no un error.",
        "",
        "## Alerta de degradación",
        "",
        alerta["mensaje"],
        "",
    ]
    if alerta.get("wape_movil") is not None:
        L += [
            f"- WAPE móvil ({alerta['ventana_cortes']} cortes: "
            f"{', '.join(alerta['cortes_en_ventana'])}): **{alerta['wape_movil']:.4f}**",
            f"- WAPE del backtest del champion ({alerta['modelo_referencia']}): "
            f"{_fmt(alerta['wape_referencia'])}",
            f"- Umbral: +{alerta['umbral_degradacion']:.0%} (solo advertencia, sin reentrenamiento "
            "automático)",
            "",
        ]
    L += ["## Desempeño por corte (última revisión de cada corte)", ""]
    if ultima.empty:
        L += ["No hay publicaciones visibles en esta fecha.", ""]
    else:
        t = ultima.assign(corte=ultima["corte"].dt.date.astype(str))
        L += [
            _tabla(
                t,
                [
                    ("corte", "Corte", ""),
                    ("revision", "Rev", "d"),
                    ("estado", "Estado", ""),
                    ("dias_con_real", "Días con real", "d"),
                    ("wape", "WAPE", ".4f"),
                    ("rmsle", "RMSLE", ".4f"),
                    ("sesgo", "Sesgo", "+.3f"),
                    ("cobertura_p10_p90", "Cobertura P10–P90", ".3f"),
                    ("costo_estado", "Costo", ""),
                    ("costo_total", "Costo total", ",.0f"),
                    ("fill_rate", "Fill rate", ".4f"),
                ],
            ),
            "",
        ]
    pend = por_corte[(por_corte["dias_sin_real"] != "")]
    L += ["## Real pendiente (días que ya debieron llegar y faltan)", ""]
    if pend.empty:
        L += ["Ninguno.", ""]
    else:
        for r in pend.itertuples():
            dias = r.dias_sin_real.replace(";", ", ")
            L.append(f"- Corte {r.corte.date()} rev={r.revision}: sin real el {dias}")
        L.append("")
    revs = por_corte[por_corte["revision"] > 1]
    L += ["## Revisiones emitidas por correcciones", ""]
    if revs.empty:
        L += ["Ninguna.", ""]
    else:
        t = revs.assign(
            corte=revs["corte"].dt.date.astype(str),
            emitido_en=revs["emitido_en"].dt.date.astype(str),
        )
        L += [
            _tabla(
                t,
                [
                    ("corte", "Corte", ""),
                    ("revision", "Rev", "d"),
                    ("emitido_en", "Emitida en", ""),
                    ("estado", "Estado", ""),
                    ("wape", "WAPE", ".4f"),
                ],
            ),
            "",
        ]
    L += ["## Desempeño por familia (ventana móvil)", ""]
    if familias.empty:
        L += ["Sin cortes suficientes.", ""]
    else:
        L += [
            _tabla(
                familias,
                [
                    ("family", "Familia", ""),
                    ("wape", "WAPE", ".4f"),
                    ("costo_total", "Costo", ",.0f"),
                ],
            ),
            "",
        ]
    if graficos:
        L += ["## Gráficos", ""]
        for titulo, ruta in graficos:
            L += [f"![{titulo}]({ruta.name})", ""]
    return "\n".join(L).rstrip() + "\n"


def publicar_reporte_reciente(dir_data: Path, destino: Path) -> Path | None:
    """Copia el reporte más reciente (y sus PNG) a `destino/seguimiento.md` (lo usa la fase 8).

    Las imágenes se copian como `destino/seguimiento_<nombre>.png` y se reescriben los enlaces.
    """
    reportes = sorted(dir_reportes(dir_data).glob("*.md"))
    if not reportes:
        return None
    ultimo = reportes[-1]
    texto = ultimo.read_text(encoding="utf-8")
    destino.mkdir(parents=True, exist_ok=True)
    for png in sorted(dir_reportes(dir_data).glob(f"{ultimo.stem}_*.png")):
        nuevo = f"seguimiento_{png.name[len(ultimo.stem) + 1 :]}"
        shutil.copyfile(png, destino / nuevo)
        texto = re.sub(rf"\]\({re.escape(png.name)}\)", f"]({nuevo})", texto)
    salida = destino / "seguimiento.md"
    _escribir_atomico(salida, texto.encode("utf-8"))
    return salida


# --------------------------------------------------------------------------------------------
# Punto de entrada
# --------------------------------------------------------------------------------------------


def _redondeo(v, n: int = 6):
    return None if v is None or pd.isna(v) else round(float(v), n)


def _resumen(corte_eval: date, por_corte: pd.DataFrame, alerta: dict) -> dict:
    filas = [
        {
            "corte": r.corte.date().isoformat(),
            "revision": int(r.revision),
            "estado": r.estado,
            "dias_con_real": int(r.dias_con_real),
            "wape": _redondeo(r.wape),
            "cobertura_p10_p90": _redondeo(r.cobertura_p10_p90),
            "costo_estado": r.costo_estado,
            "costo_total": _redondeo(r.costo_total, 2),
        }
        for r in por_corte.itertuples()
    ]
    return {
        "corte_evaluacion": corte_eval.isoformat(),
        "publicaciones": len(filas),
        "revisiones": [f"{f['corte']}/rev={f['revision']}" for f in filas if f["revision"] > 1],
        "alerta": alerta,
        "cortes": filas,
    }


def evaluar_publicados(corte_eval: date, dir_data: Path, cfgs: Configs) -> pd.DataFrame:
    """Recalcula el seguimiento as-of `corte_eval`, lo escribe y devuelve `metricas_por_corte`."""
    dir_data = Path(dir_data)
    pubs = listar_publicaciones(dir_data, corte_eval)
    particion = dir_monitoreo(dir_data, corte_eval)
    base_reporte = dir_reportes(dir_data) / corte_eval.isoformat()
    if not pubs:
        log.info("seguimiento %s: no hay publicaciones visibles", corte_eval)
        alerta = evaluar_alerta(pd.DataFrame(), corte_eval, dir_data, cfgs)
        resumen = _resumen(corte_eval, pd.DataFrame(), alerta)
        _escribir_json(particion / "resumen.json", resumen)
        return pd.DataFrame()

    ventas = asof("ventas", corte_eval, dir_data)
    desde = pd.Timestamp(min(p["corte"] for p in pubs))
    ventas = ventas[ventas["fecha_dato"] >= desde]
    reales = ventas[["fecha_dato", "store_nbr", "family", "sales"]].assign(
        store_nbr=lambda d: d["store_nbr"].astype(int), family=lambda d: d["family"].astype(str)
    )
    fechas_con_real = set(reales["fecha_dato"].unique())

    cortes, familias, horizontes = [], [], []
    for p in pubs:
        c, f, h = _evaluar_publicacion(p, reales, fechas_con_real, corte_eval, cfgs)
        cortes.append(c)
        familias += f
        horizontes += h
    por_corte = pd.DataFrame(cortes).sort_values(["corte", "revision"]).reset_index(drop=True)
    por_familia = pd.DataFrame(familias or {c: [] for c in COLS_FAMILIA}).sort_values(COLS_FAMILIA)
    por_h = pd.DataFrame(horizontes or {c: [] for c in COLS_H}).sort_values(COLS_H)

    alerta = evaluar_alerta(por_corte, corte_eval, dir_data, cfgs)
    ultima = por_corte.groupby("corte").tail(1).reset_index(drop=True)
    ventana = ventana_alerta(por_corte, cfgs)
    fam_ventana = _familias_ventana(por_familia, ventana)
    graficos = _graficos(ultima, fam_ventana, alerta, base_reporte)

    escribir_parquet(por_corte, particion / "metricas_por_corte.parquet")
    if len(por_familia):
        escribir_parquet(
            por_familia.reset_index(drop=True), particion / "metricas_por_familia.parquet"
        )
        escribir_parquet(por_h.reset_index(drop=True), particion / "metricas_por_h.parquet")
    _escribir_json(particion / "resumen.json", _resumen(corte_eval, por_corte, alerta))
    md = _reporte_md(corte_eval, por_corte, ultima, fam_ventana, alerta, graficos)
    _escribir_atomico(base_reporte.with_name(base_reporte.name + ".md"), md.encode("utf-8"))
    log.info("seguimiento %s: %d publicaciones; %s", corte_eval, len(por_corte), alerta["mensaje"])
    return por_corte


def _escribir_json(ruta: Path, contenido: dict) -> None:
    texto = json.dumps(contenido, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    _escribir_atomico(ruta, texto.encode("utf-8"))


def leer_resumen(dir_data: Path, corte_eval: date) -> dict | None:
    """`resumen.json` del seguimiento de `corte_eval`, o `None` si todavía no se calculó."""
    ruta = dir_monitoreo(dir_data, corte_eval) / "resumen.json"
    return json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else None
