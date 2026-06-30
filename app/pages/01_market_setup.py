"""Market Setup: selector de partido del Mundial -> Polymarket -> calibrar -> analitica.

Pagina delgada y SIN inputs numericos manuales. El usuario elige un partido del
Mundial 2026 desde un selector poblado en vivo desde Polymarket; la pagina lee
precios (1X2 + O/U + BTTS), calibra el modelo, guarda el resultado en sesion
(compatible con Live Match) y despliega el catalogo analitico mas Modelo vs
Mercado. Nada de matematica inline: todo vive en src/models/* y src/connectors/*.
"""
import os
import sys
from datetime import datetime

# --- bootstrap de sys.path (archivo en app/pages/ -> subir DOS niveles) -----
_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), os.pardir, os.pardir)
)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import plotly.graph_objects as go
import streamlit as st

from src.connectors import polymarket as pm
from src.dashboard import state
from src.models import analytics, calibration, dixon_coles, poisson
from src.utils.config import load_config

st.set_page_config(page_title="Market Setup", page_icon="🎯")

cfg = load_config()
pm_cfg = load_config(section="polymarket")
_LIST_TTL = int(pm_cfg.get("list_cache_ttl_seconds", 120))


# --- Carga cacheada desde Polymarket --------------------------------------
# Las funciones cacheadas llaman a pm.* por atributo de modulo, para que un
# patch sobre pm.list_world_cup_matches / pm.get_match_markets tenga efecto.
# El parametro `nonce` forma parte de la clave de cache: al incrementarlo (boton
# de refresco) se fuerza un cache-miss SIN usar st.rerun() (que reseteaba la
# seleccion del selectbox). Cada cache es independiente (lista vs mercados).
@st.cache_data(ttl=_LIST_TTL, show_spinner="Cargando partidos del Mundial...")
def _load_match_list(nonce: int):
    return pm.list_world_cup_matches()


@st.cache_data(ttl=_LIST_TTL, show_spinner="Cargando mercados del partido...")
def _load_match_markets(slug: str, nonce: int):
    # Devuelve tambien el instante del fetch real. Como cache_data cachea el
    # valor de retorno, el timestamp queda "congelado" junto con los datos:
    # en cache-hit refleja cuando se trajeron, y solo cambia al refrescar.
    return pm.get_match_markets(slug), datetime.now()


# Nonces de refresco (parte de la clave de cache). No los toca st.rerun().
st.session_state.setdefault("setup_list_nonce", 0)
st.session_state.setdefault("setup_markets_nonce", 0)


st.title("🎯 Market Setup")
st.caption(
    "Elige un partido del Mundial 2026. Los precios se leen en vivo desde "
    "Polymarket; el modelo se calibra solo."
)

# --- Selector de partido ---------------------------------------------------
col_sel, col_btn = st.columns([5, 1])
with col_btn:
    st.write("")
    if st.button("🔄 Actualizar lista", key="setup_refresh_btn"):
        # El click ya provoca un rerun natural; solo invalidamos la cache de la
        # lista bumpeando su nonce. Nada de st.rerun() (resetearia el selector).
        st.session_state["setup_list_nonce"] += 1

try:
    matches = _load_match_list(st.session_state["setup_list_nonce"])
except pm.PolymarketError as exc:
    st.error(f"No se pudo cargar la lista de partidos: {exc}")
    st.stop()

if not matches:
    st.warning("No hay partidos del Mundial disponibles ahora mismo.")
    st.stop()


def _fmt_match(m):
    fecha = (m.start_date or "")[:10]
    return f"{m.home_team} vs {m.away_team} — {fecha} (liq ${m.total_liquidity:,.0f})"


def _period_label(status: str, minute) -> str:
    """Texto del periodo para el banner live."""
    if status == "halftime":
        return "Entretiempo"
    if minute is not None and minute <= 45:
        return "1er tiempo"
    return "2do tiempo"


def _render_state_banner(live, start_date: str):
    """Estado actual del partido, visible siempre en la cabecera (pre/live/post)."""
    h = live.home_score if live.home_score is not None else 0
    a = live.away_score if live.away_score is not None else 0
    if live.status == "halftime":
        st.warning(f"🟡 ENTRETIEMPO · {h}-{a}")
    elif live.status == "in":
        minute_txt = "—" if live.minute is None else f"{live.minute:.0f}'"
        st.success(
            f"🟢 EN VIVO · min {minute_txt} · {h}-{a} · "
            f"{_period_label(live.status, live.minute)}"
        )
    elif live.status == "post":
        st.error(f"🏁 Finalizado · {h}-{a}")
    else:  # pre
        inicio = (start_date or "")[:16].replace("T", " ")
        sufijo = f" · inicia {inicio} UTC" if inicio else ""
        st.info(f"🔵 Aún no comienza{sufijo}")


# El selectbox usa el `slug` (string estable) como valor, NO el objeto
# MatchSummary. Motivo: st.cache_data devuelve copias nuevas en cada rerun y la
# igualdad por campos se rompe al cambiar liquidez/volumen tras un refresh, lo
# que reseteaba la seleccion al primer partido. El slug no cambia con el refetch.
by_slug = {m.slug: m for m in matches}
with col_sel:
    selected_slug = st.selectbox(
        "Partido",
        options=list(by_slug.keys()),
        format_func=lambda s: _fmt_match(by_slug[s]),
        key="setup_match_select",
    )
selected = by_slug[selected_slug]

# --- Cabecera del partido + refresco de precios ----------------------------
# El boton va ANTES de la carga: al hacer click bumpeamos el nonce de mercados
# y el refetch ocurre en este mismo run (sin st.rerun()). El titulo usa el
# partido elegido de la lista para no depender aun de la carga de mercados.
st.divider()
head_l, head_r = st.columns([4, 1])
with head_l:
    st.subheader(f"📊 {selected.home_team} vs {selected.away_team}")
with head_r:
    st.write("")
    if st.button("🔄 Actualizar precios", key="setup_refresh_prices_btn"):
        st.session_state["setup_markets_nonce"] += 1

# --- Carga de mercados del partido elegido (con el nonce ya actualizado) ----
try:
    mm, fetched_at = _load_match_markets(
        selected.slug, st.session_state["setup_markets_nonce"]
    )
except pm.PolymarketError as exc:
    st.error(f"No se pudieron cargar los mercados del partido: {exc}")
    st.stop()

home_team = mm.summary.home_team
away_team = mm.summary.away_team
match_name = f"{home_team} vs {away_team}"

st.caption(
    f"Inicio: {mm.summary.start_date[:16]}  ·  slug: `{mm.summary.slug}`  ·  "
    f"Última actualización: {fetched_at:%H:%M:%S}"
)

# --- Estado del partido (time-aware): banner visible siempre ----------------
# El connector ya parsea el minuto + marcador desde el mismo evento Gamma.
live = mm.live
status = live.status  # "pre" | "in" | "halftime" | "post"
is_live = status in ("in", "halftime")
max_goals = cfg["max_goals"]
_render_state_banner(live, mm.summary.start_date)

# --- Precios 1X2 con spread y liquidez por mercado (senal confiable) -------
st.markdown("### Precios 1X2 (mercado)")
required = {"home", "draw", "away"}
if not required.issubset(mm.one_x_two) or any(
    mm.one_x_two[name].price is None for name in required
):
    st.error("El partido no tiene los 3 mercados 1X2 completos. Elige otro.")
    st.stop()

q_home = mm.one_x_two["home"]
q_draw = mm.one_x_two["draw"]
q_away = mm.one_x_two["away"]

pc1, pc2, pc3 = st.columns(3)
for col, label, q in (
    (pc1, f"{home_team} (local)", q_home),
    (pc2, "Empate", q_draw),
    (pc3, f"{away_team} (visita)", q_away),
):
    spread = "—" if q.spread is None else f"{q.spread:.3f}"
    liq = "—" if q.liquidity is None else f"${q.liquidity:,.0f}"
    col.metric(label, f"{q.price:.3f}", help=f"spread {spread} · liq {liq}")
    col.caption(f"spread {spread} · liq {liq}")

st.caption(
    "El spread de los mercados 1X2 es la senal confiable (suele ser ~0.01 en "
    "partidos grandes). El flag agregado de calidad puede salir **HIGH_SPREAD** "
    "por lineas O/U extremas y delgadas; no contamina el 1X2."
)
if mm.quality_flags and mm.quality_flags != ["OK"]:
    st.warning(f"Flags de calidad (agregados): {', '.join(mm.quality_flags)}")

# --- Caso TERMINADO: marcador final, sin calibracion ni proyeccion ---------
if status == "post":
    h = live.home_score if live.home_score is not None else "?"
    a = live.away_score if live.away_score is not None else "?"
    st.markdown(f"### 🏁 Resultado final: **{h} - {a}**")
    st.info(
        "Partido terminado. Los precios ya no son accionables, por lo que no se "
        "calibra el modelo ni se muestra proyeccion."
    )
    st.stop()

# --- Selector de modelo (default Dixon-Coles) ------------------------------
model_label = st.radio(
    "Modelo",
    options=["Dixon-Coles", "Poisson"],
    index=0,
    horizontal=True,
    key="setup_model_label",
)
model_type = "dixon_coles" if model_label == "Dixon-Coles" else "poisson"

# --- Calibracion (time-aware) ----------------------------------------------
normalized = calibration.normalize_prices(q_home.price, q_draw.price, q_away.price)

if is_live:
    # LIVE: el estado ya se muestra en el banner de cabecera. Aqui solo se
    # calibran los lambdas RESTANTES condicionados al marcador actual, contra
    # el precio live. El minuto solo se muestra (no entra en la matematica).
    h_score = live.home_score or 0
    a_score = live.away_score or 0

    cal = calibration.calibrate_remaining(
        normalized,
        h_score,
        a_score,
        model=model_type,
        config=cfg,
    )
    lambda_home = cal["lambda_home_remaining"]
    lambda_away = cal["lambda_away_remaining"]
    rho = cal["rho"]

    # Matriz de goles RESTANTES -> matriz del marcador FINAL (desplazada por H,A).
    if model_type == "dixon_coles":
        remaining_matrix = dixon_coles.score_matrix(lambda_home, lambda_away, rho, max_goals)
    else:
        remaining_matrix = poisson.score_matrix(lambda_home, lambda_away, max_goals)
    matrix = analytics.final_score_matrix(remaining_matrix, h_score, a_score, max_goals)

    # Guardar en sesion: lambdas RESTANTES + bloque live en metadata.
    metadata = {
        "home_team": home_team,
        "away_team": away_team,
        "match_name": match_name,
        "model_type": model_type,
        "slug": mm.summary.slug,
        "start_date": mm.summary.start_date,
        "live": {
            "minute": live.minute,
            "home_score": h_score,
            "away_score": a_score,
            "status": status,
        },
    }
    state.save_model(
        metadata=metadata,
        calibration_result={
            "lambda_home": lambda_home,
            "lambda_away": lambda_away,
            "rho": rho,
        },
        market_probs=normalized,
        config=cfg,
    )

    lc1, lc2, lc3 = st.columns(3)
    lc1.metric("λ local restante", f"{lambda_home:.3f}")
    lc2.metric("λ visita restante", f"{lambda_away:.3f}")
    lc3.metric("ρ", f"{rho:.3f}")
    st.caption(
        "En vivo: los λ representan los goles que **quedan** por anotar, "
        "calibrados al precio live y condicionados al marcador actual."
    )
    if cal["warnings"]:
        for w in cal["warnings"]:
            st.warning(w)
    else:
        st.caption("Calibracion OK: el modelo reproduce bien el precio live.")
else:
    # PRE-PARTIDO: comportamiento de siempre (90 min desde 0-0). El estado ya
    # se muestra en el banner de cabecera.
    over_2_5_price = mm.over_under[2.5].price if 2.5 in mm.over_under else None
    result = calibration.calibrate(
        normalized,
        model=model_type,
        over_2_5_price=over_2_5_price,
        config=cfg,
    )

    metadata = {
        "home_team": home_team,
        "away_team": away_team,
        "match_name": match_name,
        "model_type": model_type,
        "slug": mm.summary.slug,
        "start_date": mm.summary.start_date,
    }
    state.save_model(
        metadata=metadata,
        calibration_result=result,
        market_probs=normalized,
        config=cfg,
    )

    lambda_home = result["lambda_home"]
    lambda_away = result["lambda_away"]
    rho = result["rho"]

    if model_type == "dixon_coles":
        matrix = dixon_coles.score_matrix(lambda_home, lambda_away, rho, max_goals)
    else:
        matrix = poisson.score_matrix(lambda_home, lambda_away, max_goals)

    lc1, lc2, lc3 = st.columns(3)
    lc1.metric("λ local", f"{lambda_home:.3f}")
    lc2.metric("λ visita", f"{lambda_away:.3f}")
    lc3.metric("ρ", f"{rho:.3f}")
    if result["warnings"]:
        for w in result["warnings"]:
            st.warning(w)
    else:
        st.caption("Calibracion OK: el modelo reproduce bien los precios 1X2.")

# ===========================================================================
# Modelo vs Mercado (pieza central)
# ===========================================================================
st.divider()
st.markdown("## ⚖️ Modelo vs Mercado")
if is_live:
    st.caption(
        "En vivo: el modelo se evalua sobre la **proyeccion final** (marcador "
        "actual + goles restantes) contra el precio live. "
        "Edge = modelo − mercado, ordenado por |edge|."
    )
else:
    st.caption("Edge = probabilidad del modelo − precio de mercado. Ordenado por |edge|.")

market_quotes = [
    {"market": "home", "market_price": q_home.price},
    {"market": "draw", "market_price": q_draw.price},
    {"market": "away", "market_price": q_away.price},
]
for line in analytics.SUPPORTED_OU_LINES:
    if line in mm.over_under and mm.over_under[line].price is not None:
        market_quotes.append(
            {"market": f"over_{line}", "market_price": mm.over_under[line].price}
        )
if mm.btts is not None and mm.btts.price is not None:
    market_quotes.append({"market": "btts", "market_price": mm.btts.price})

mvm = analytics.model_vs_market(matrix, lambda_home, lambda_away, market_quotes)

_LABELS = {
    "home": f"Gana {home_team}",
    "draw": "Empate",
    "away": f"Gana {away_team}",
    "btts": "Ambos anotan (BTTS)",
}


def _market_label(name: str) -> str:
    if name in _LABELS:
        return _LABELS[name]
    if name.startswith("over_"):
        return f"Over {name[len('over_'):]}"
    return name


def _edge_arrow(edge):
    if edge is None:
        return ""
    if edge > 0.01:
        return "🟢 ▲"
    if edge < -0.01:
        return "🔴 ▼"
    return "⚪ ·"


mvm_rows = [
    {
        "Mercado": _market_label(r["market"]),
        "Modelo": "—" if r["model_prob"] is None else f"{r['model_prob']:.3f}",
        "Mercado (precio)": f"{r['market_price']:.3f}",
        "Edge": "—" if r["edge"] is None else f"{r['edge']:+.3f}",
        "": _edge_arrow(r["edge"]),
    }
    for r in mvm
]
st.dataframe(mvm_rows, use_container_width=True, hide_index=True, key="setup_mvm_table")

# ===========================================================================
# Catalogo analitico
# ===========================================================================
st.divider()
if is_live:
    st.markdown("## 📈 Proyección final (en vivo)")
    st.caption(
        "Todas las cifras son del **resultado final** proyectado: marcador "
        "actual mas los goles que aun quedan por anotar."
    )
else:
    st.markdown("## 📈 Analitica del partido")

probs = analytics.one_x_two(matrix)
dc = analytics.double_chance(probs)

# --- Resumen ---------------------------------------------------------------
st.markdown("### Resumen")
rc1, rc2, rc3 = st.columns(3)
rc1.metric(f"P(gana {home_team})", f"{probs['home']:.3f}")
rc2.metric("P(empate)", f"{probs['draw']:.3f}")
rc3.metric(f"P(gana {away_team})", f"{probs['away']:.3f}")

if is_live:
    # Goles esperados live: marcado vs restante vs total proyectado.
    egl = analytics.expected_goals_live(h_score, a_score, lambda_home, lambda_away)
    st.markdown("**Goles esperados (marcado · restante · total proyectado)**")
    egc1, egc2, egc3 = st.columns(3)
    egc1.metric(
        f"{home_team}",
        f"{egl['home_total']:.2f}",
        help=f"marcado {egl['home_scored']:.0f} + restante {egl['home_remaining']:.2f}",
    )
    egc1.caption(f"{egl['home_scored']:.0f} marcado + {egl['home_remaining']:.2f} restante")
    egc2.metric(
        f"{away_team}",
        f"{egl['away_total']:.2f}",
        help=f"marcado {egl['away_scored']:.0f} + restante {egl['away_remaining']:.2f}",
    )
    egc2.caption(f"{egl['away_scored']:.0f} marcado + {egl['away_remaining']:.2f} restante")
    egc3.metric("Total proyectado", f"{egl['total']:.2f}")
else:
    eg = analytics.expected_goals(lambda_home, lambda_away)
    eg1, eg2, eg3 = st.columns(3)
    eg1.metric("Goles esperados local", f"{eg['home']:.2f}")
    eg2.metric("Goles esperados visita", f"{eg['away']:.2f}")
    eg3.metric("Goles esperados total", f"{eg['total']:.2f}")

st.markdown("**Doble oportunidad**")
dcols = st.columns(3)
dcols[0].metric("1X (local o empate)", f"{dc['home_or_draw']:.3f}")
dcols[1].metric("12 (sin empate)", f"{dc['home_or_away']:.3f}")
dcols[2].metric("X2 (empate o visita)", f"{dc['draw_or_away']:.3f}")

# --- Goles -----------------------------------------------------------------
st.markdown("### Goles")
tgd = analytics.total_goals_distribution(matrix, up_to=5)
tgd_labels = [str(k) for k in tgd.keys()]
tgd_values = [tgd[k] for k in tgd.keys()]

fig_goals = go.Figure(go.Bar(x=tgd_labels, y=tgd_values, marker_color="#4C78A8"))
fig_goals.update_layout(
    title="Distribucion de goles totales",
    xaxis_title="Goles en el partido",
    yaxis_title="Probabilidad",
)
st.plotly_chart(fig_goals, use_container_width=True)

# Over/Under por linea (modelo) + comparativa con mercado donde exista.
ou_lines = list(analytics.SUPPORTED_OU_LINES)
ou_model_over = [analytics.over_under(matrix, line)["over"] for line in ou_lines]
ou_table = [
    {
        "Linea": f"{line}",
        "Over (modelo)": f"{analytics.over_under(matrix, line)['over']:.3f}",
        "Under (modelo)": f"{analytics.over_under(matrix, line)['under']:.3f}",
        "Over (mercado)": (
            f"{mm.over_under[line].price:.3f}"
            if line in mm.over_under and mm.over_under[line].price is not None
            else "—"
        ),
    }
    for line in ou_lines
]
st.markdown("**Over/Under por linea**")
st.table(ou_table)

# Grafico agrupado modelo vs mercado por linea O/U.
market_over = [
    mm.over_under[line].price if line in mm.over_under else None for line in ou_lines
]
fig_ou = go.Figure()
fig_ou.add_trace(go.Bar(name="Over (modelo)", x=[str(l) for l in ou_lines], y=ou_model_over))
fig_ou.add_trace(go.Bar(name="Over (mercado)", x=[str(l) for l in ou_lines], y=market_over))
fig_ou.update_layout(
    title="Over por linea: modelo vs mercado",
    barmode="group",
    xaxis_title="Linea O/U",
    yaxis_title="P(Over)",
)
st.plotly_chart(fig_ou, use_container_width=True)

# BTTS + clean sheets.
bt = analytics.btts(matrix)
cs = analytics.clean_sheets(matrix)
gc1, gc2, gc3, gc4 = st.columns(4)
gc1.metric("BTTS Si", f"{bt['yes']:.3f}")
gc2.metric("BTTS No", f"{bt['no']:.3f}")
gc3.metric(f"Valla invicta {home_team}", f"{cs['home']:.3f}")
gc4.metric(f"Valla invicta {away_team}", f"{cs['away']:.3f}")

# --- Dinamica --------------------------------------------------------------
st.markdown("### Dinamica")
if is_live:
    # "Proximo en anotar" sobre los lambdas RESTANTES (el orden real del primer
    # gol no es recuperable solo del marcador). Si va 0-0 equivale al primer gol.
    nts = analytics.next_to_score(lambda_home, lambda_away)
    fc1, fc2, fc3 = st.columns(3)
    fc1.metric(f"Próximo en anotar: {home_team}", f"{nts['home']:.3f}")
    fc2.metric(f"Próximo en anotar: {away_team}", f"{nts['away']:.3f}")
    fc3.metric("Sin mas goles", f"{nts['none']:.3f}")
else:
    fts = analytics.first_to_score(lambda_home, lambda_away)
    fc1, fc2, fc3 = st.columns(3)
    fc1.metric(f"Primero en anotar: {home_team}", f"{fts['home']:.3f}")
    fc2.metric(f"Primero en anotar: {away_team}", f"{fts['away']:.3f}")
    fc3.metric("Sin goles", f"{fts['none']:.3f}")

wm = analytics.winning_margin(matrix)
wm_table = [
    {"Resultado": f"{home_team} por 1", "Prob.": f"{wm['home_by_1']:.3f}"},
    {"Resultado": f"{home_team} por 2", "Prob.": f"{wm['home_by_2']:.3f}"},
    {"Resultado": f"{home_team} por 3+", "Prob.": f"{wm['home_by_3+']:.3f}"},
    {"Resultado": "Empate", "Prob.": f"{wm['draw']:.3f}"},
    {"Resultado": f"{away_team} por 1", "Prob.": f"{wm['away_by_1']:.3f}"},
    {"Resultado": f"{away_team} por 2", "Prob.": f"{wm['away_by_2']:.3f}"},
    {"Resultado": f"{away_team} por 3+", "Prob.": f"{wm['away_by_3+']:.3f}"},
]
st.markdown("**Margen de victoria**")
st.table(wm_table)

# --- Marcadores ------------------------------------------------------------
st.markdown("### Marcadores mas probables (top 10)")
top = analytics.top_scores(matrix, 10)
top_rows = [{"Marcador": f"{h}-{a}", "Probabilidad": f"{p:.3f}"} for h, a, p in top]
st.table(top_rows)
