"""Live Match: monitor en vivo auto-refrescado del partido en análisis.

Reutiliza el modelo calibrado en Market Setup (por slug), sondea Polymarket en
un st.fragment(run_every=...), acumula snapshots en una serie de sesión y
renderiza scoreboard + KPIs + Gráfico A (win-probability) + Gráfico C (escáner
de edge multi-mercado). Sin inputs manuales; nada de matemática inline.
"""
import os
import sys
from datetime import datetime

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import plotly.graph_objects as go
import streamlit as st

from src.connectors import polymarket as pm
from src.dashboard import logic, state
from src.utils.config import load_config

st.set_page_config(page_title="Live Match", page_icon="🟢")

cfg = load_config()
_REFRESH = int(load_config(section="live").get("live_refresh_seconds", 30))

st.title("🟢 Live Match")

# --- Guard: requiere modelo calibrado en Market Setup ----------------------
model = state.get_model()
if model is None:
    st.warning("Calibra primero en Market Setup")
    st.stop()

meta = model["metadata"]
slug = meta.get("slug")
home_team = meta.get("home_team", "Local")
away_team = meta.get("away_team", "Visita")
st.subheader(meta.get("match_name", "Partido"))

if not slug:
    st.error("El modelo guardado no tiene slug. Recalibra en Market Setup.")
    st.stop()

# --- Controles -------------------------------------------------------------
c1, c2, c3 = st.columns([2, 1, 1])
with c1:
    auto_on = st.toggle(f"Auto-refresco (cada {_REFRESH}s)", value=True, key="live_auto")
with c2:
    st.button("↻ Actualizar ahora", key="live_refresh_now")  # el click dispara un rerun completo que vuelve a ejecutar el fragmento
with c3:
    if st.button("🗑 Reiniciar serie", key="live_reset_series"):
        state.reset_series()

# run_every se apaga si Auto está OFF o si el partido ya terminó (auto-stop).
_last_status = st.session_state.get("live_last_status")
run_every = None if (_last_status == "post" or not auto_on) else f"{_REFRESH}s"


def _period_label(status, minute):
    if status == "halftime":
        return "Entretiempo"
    if minute is not None and minute <= 45:
        return "1er tiempo"
    return "2do tiempo"


def _scoreboard(live):
    h = live.home_score if live.home_score is not None else 0
    a = live.away_score if live.away_score is not None else 0
    if live.status == "post":
        st.error(f"🏁 Finalizado · {home_team} {h} – {a} {away_team}")
    elif live.status in ("in", "halftime"):
        minute_txt = "—" if live.minute is None else f"{live.minute:.0f}'"
        st.success(
            f"🟢 EN VIVO · min {minute_txt} · {home_team} {h} – {a} {away_team} · "
            f"{_period_label(live.status, live.minute)}"
        )
    else:
        st.info(f"🔵 Aún no comienza · {home_team} vs {away_team}")


def _render_kpis(snap):
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric(f"P(gana {home_team})", f"{snap['model_home_prob']:.3f}")
    k2.metric("P(empate)", f"{snap['model_draw_prob']:.3f}")
    k3.metric(f"P(gana {away_team})", f"{snap['model_away_prob']:.3f}")
    k4.metric("Edge empate", f"{snap['edge']:+.3f}")
    best = snap.get("best_opportunity")
    if best is not None:
        k5.metric("Mejor oportunidad", logic.market_label(best["market"]), f"{best['edge']:+.3f}")
    else:
        k5.metric("Mejor oportunidad", "—")


def _render_chart_a(series):
    st.markdown("**📈 A · Probabilidades del resultado final en el tiempo**")
    if not series:
        st.info("Esperando datos en vivo…")
        return
    mins = [s["minute"] for s in series]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=mins, y=[s["model_home_prob"] for s in series],
                             mode="lines+markers", name=f"Gana {home_team}",
                             line=dict(color="#4C78A8")))
    fig.add_trace(go.Scatter(x=mins, y=[s["model_draw_prob"] for s in series],
                             mode="lines+markers", name="Empate",
                             line=dict(color="#E1A33A")))
    fig.add_trace(go.Scatter(x=mins, y=[s["model_away_prob"] for s in series],
                             mode="lines+markers", name=f"Gana {away_team}",
                             line=dict(color="#C0504D")))
    for mk in logic.goal_markers(series):
        fig.add_vline(x=mk["minute"], line_dash="dash", line_color="gray")
        fig.add_annotation(x=mk["minute"], y=1.0,
                           text=f"⚽ {mk['home_score']}-{mk['away_score']}",
                           showarrow=False, font=dict(size=10))
    fig.update_layout(xaxis_title="Minuto", yaxis_title="Probabilidad", yaxis_range=[0, 1])
    st.plotly_chart(fig, use_container_width=True)


def _render_chart_c(snap):
    st.markdown("**🎯 C · Escáner de edge por mercado (ordenado por |edge|)**")
    rows = [e for e in snap.get("edges", []) if e["edge"] is not None]
    if not rows:
        st.info("Sin mercados comparables aún.")
        return
    labels = [logic.market_label(e["market"]) for e in rows][::-1]
    values = [e["edge"] for e in rows][::-1]
    colors = ["#4C9A6A" if v > 0 else "#C0504D" for v in values]
    fig = go.Figure(go.Bar(x=values, y=labels, orientation="h", marker_color=colors))
    fig.add_vline(x=0.0, line_color="gray")
    fig.update_layout(xaxis_title="Edge (modelo − mercado)")
    st.plotly_chart(fig, use_container_width=True)


@st.fragment(run_every=run_every)
def live_panel():
    try:
        mm = pm.get_match_markets(slug)
    except Exception as exc:  # red caída: conservar la serie, no caerse
        st.warning(f"No se pudo actualizar ahora ({exc}). Se conserva la última serie.")
        return

    live = mm.live
    _scoreboard(live)

    if live.status == "in" and live.minute is not None:
        state.append_live_snapshot(slug, logic.build_live_snapshot(model, mm, cfg))
    elif live.status == "halftime":
        st.caption("Entretiempo: el modelo no se actualiza hasta el reinicio.")
    elif live.status == "post":
        st.caption("Partido finalizado: auto-refresco detenido.")

    series = state.get_series()
    st.caption(f"Última actualización: {datetime.now():%H:%M:%S} · {len(series)} snapshots")
    if series:
        _render_kpis(series[-1])
    st.divider()
    _render_chart_a(series)
    _render_chart_c(series[-1] if series else {})

    # Auto-stop / re-sync del timer: si el estado actual cambia lo que debería ser
    # run_every (p. ej. el partido pasó a 'post', o se reanudó), re-corre la app
    # una vez para recomputar run_every. Converge porque el outer lee el estado ya
    # actualizado en la próxima pasada.
    st.session_state["live_last_status"] = live.status
    desired_off = (live.status == "post") or (not auto_on)
    if desired_off != (run_every is None):
        st.rerun()


live_panel()
