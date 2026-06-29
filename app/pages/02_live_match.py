"""Live Match: estado live → probabilidades + edge + gráficos.

Página delgada: lee inputs, construye un MatchState, llama a logic.build_snapshot
y a logic.forward_draw_curve, y renderiza con Plotly. Nada de matemática inline.
"""
import os
import sys

# --- bootstrap de sys.path (archivo en app/pages/ -> subir DOS niveles) -----
_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), os.pardir, os.pardir)
)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import plotly.graph_objects as go
import streamlit as st

from src.dashboard import logic, state
from src.models.live_update import MatchState
from src.utils.config import load_config

st.set_page_config(page_title="Live Match", page_icon="🟢")

cfg = load_config()

st.title("🟢 Live Match")

# --- Guard: requiere modelo calibrado --------------------------------------
model = state.get_model()
if model is None:
    st.warning("Calibra primero en Market Setup")
    st.stop()

meta = model["metadata"]
st.subheader(meta.get("match_name", "Partido"))
hc1, hc2, hc3, hc4 = st.columns(4)
hc1.metric(meta.get("home_team", "Local"), f"λ {model['lambda_home']:.3f}")
hc2.metric(meta.get("away_team", "Visita"), f"λ {model['lambda_away']:.3f}")
hc3.metric("Modelo", model["model_type"])
hc4.metric("ρ", f"{model['rho']:.3f}")

st.divider()

# --- Inputs del estado live ------------------------------------------------
st.subheader("Estado del partido")
minute = st.number_input(
    "Minuto", min_value=0, max_value=90, value=0, step=1, key="live_minute"
)

sc1, sc2 = st.columns(2)
with sc1:
    home_score = st.number_input(
        "Goles local", min_value=0, max_value=20, value=0, step=1,
        key="live_home_score",
    )
with sc2:
    away_score = st.number_input(
        "Goles visita", min_value=0, max_value=20, value=0, step=1,
        key="live_away_score",
    )

st.markdown("**xG acumulado**")
xc1, xc2 = st.columns(2)
with xc1:
    home_xg = st.number_input(
        "xG A", min_value=0.0, value=0.0, step=0.1, format="%.2f",
        key="live_home_xg",
    )
with xc2:
    away_xg = st.number_input(
        "xG B", min_value=0.0, value=0.0, step=0.1, format="%.2f",
        key="live_away_xg",
    )

st.markdown("**xG últimos 10 min**")
xl1, xl2 = st.columns(2)
with xl1:
    home_xg_last_10 = st.number_input(
        "xG últimos 10 A", min_value=0.0, value=0.0, step=0.1, format="%.2f",
        key="live_home_xg_last_10",
    )
with xl2:
    away_xg_last_10 = st.number_input(
        "xG últimos 10 B", min_value=0.0, value=0.0, step=0.1, format="%.2f",
        key="live_away_xg_last_10",
    )

st.markdown("**Tiros (opcional, no entran al cálculo aún)**")
sh1, sh2, sh3, sh4 = st.columns(4)
with sh1:
    st.number_input("Tiros A", min_value=0, value=0, step=1, key="live_shots_a")
with sh2:
    st.number_input("Al arco A", min_value=0, value=0, step=1, key="live_sot_a")
with sh3:
    st.number_input("Tiros B", min_value=0, value=0, step=1, key="live_shots_b")
with sh4:
    st.number_input("Al arco B", min_value=0, value=0, step=1, key="live_sot_b")

st.markdown("**Tarjetas rojas**")
rc1, rc2 = st.columns(2)
with rc1:
    home_red = st.number_input(
        "Rojas A", min_value=0, max_value=5, value=0, step=1, key="live_home_red"
    )
with rc2:
    away_red = st.number_input(
        "Rojas B", min_value=0, max_value=5, value=0, step=1, key="live_away_red"
    )

st.markdown("**Mercado**")
mk1, mk2, mk3 = st.columns(3)
with mk1:
    market_draw_price = st.number_input(
        "Precio empate (mercado)", min_value=0.0, max_value=1.0, value=0.20,
        step=0.01, format="%.4f", key="live_market_draw",
    )
with mk2:
    st.number_input(
        "Best bid empate", min_value=0.0, max_value=1.0, value=0.0,
        step=0.01, format="%.4f", key="live_best_bid",
    )
with mk3:
    st.number_input(
        "Best ask empate", min_value=0.0, max_value=1.0, value=0.0,
        step=0.01, format="%.4f", key="live_best_ask",
    )

# --- Helpers para opcionales: 0 => None ------------------------------------
def _opt(value):
    return value if value > 0 else None


match_state = MatchState(
    minute=minute,
    home_score=home_score,
    away_score=away_score,
    home_xg=_opt(home_xg),
    away_xg=_opt(away_xg),
    home_xg_last_10=_opt(home_xg_last_10),
    away_xg_last_10=_opt(away_xg_last_10),
    home_red_cards=home_red,
    away_red_cards=away_red,
)

snapshot = logic.build_snapshot(model, match_state, market_draw_price, cfg)

# --- Salidas live ----------------------------------------------------------
st.divider()
st.subheader("Probabilidades live")
pc1, pc2, pc3 = st.columns(3)
pc1.metric("P(local)", f"{snapshot['model_home_prob']:.3f}")
pc2.metric("P(empate)", f"{snapshot['model_draw_prob']:.3f}")
pc3.metric("P(visita)", f"{snapshot['model_away_prob']:.3f}")

ec1, ec2 = st.columns(2)
ec1.metric("Precio justo empate (ahora)", f"{snapshot['model_draw_prob']:.3f}")
ec2.metric("Edge", f"{snapshot['edge']:+.3f}")
st.info(logic.describe_edge(snapshot["edge"]))

# --- Acciones --------------------------------------------------------------
ac1, ac2 = st.columns(2)
with ac1:
    if st.button("Registrar snapshot", type="primary", key="live_register_btn"):
        state.append_snapshot(snapshot)
        st.success("Snapshot registrado.")
with ac2:
    if st.button("Limpiar snapshots", key="live_clear_btn"):
        state.clear_snapshots()
        st.success("Snapshots limpiados.")

snapshots = state.get_snapshots()
st.caption(f"Snapshots registrados: {len(snapshots)}")

# --- Gráficos --------------------------------------------------------------
st.divider()
st.subheader("Gráficos")

# 1. Curva forward del empate (del minuto actual a 90, asumiendo 0-0).
st.markdown("**1. Curva del precio justo del empate (forward)**")
curve = logic.forward_draw_curve(model, cfg, minute)
if not curve:
    st.info("No hay puntos de curva para el minuto actual.")
else:
    minutes = [p["minute"] for p in curve]
    fig1 = go.Figure()
    fig1.add_trace(go.Scatter(x=minutes, y=[p["p_draw"] for p in curve],
                              mode="lines+markers", name="P(empate)"))
    fig1.add_trace(go.Scatter(x=minutes, y=[p["p_home"] for p in curve],
                              mode="lines+markers", name="P(local)"))
    fig1.add_trace(go.Scatter(x=minutes, y=[p["p_0_0_final"] for p in curve],
                              mode="lines+markers", name="P(0-0 final)"))
    fig1.update_layout(xaxis_title="Minuto", yaxis_title="Probabilidad")
    st.plotly_chart(fig1, use_container_width=True)

# 2. Modelo vs mercado en el tiempo (de snapshots).
st.markdown("**2. Modelo (P empate) vs mercado en el tiempo**")
if not snapshots:
    st.info("Aún no hay snapshots. Registra al menos uno.")
else:
    mins = [s["minute"] for s in snapshots]
    fig2 = go.Figure()
    fig2.add_trace(go.Scatter(x=mins, y=[s["model_draw_prob"] for s in snapshots],
                              mode="lines+markers", name="Modelo P(empate)"))
    fig2.add_trace(go.Scatter(x=mins, y=[s["market_draw_price"] for s in snapshots],
                              mode="lines+markers", name="Mercado (empate)"))
    fig2.update_layout(xaxis_title="Minuto", yaxis_title="Probabilidad / precio")
    st.plotly_chart(fig2, use_container_width=True)

# 3. xG acumulado en el tiempo (de snapshots).
st.markdown("**3. xG acumulado en el tiempo**")
if not snapshots:
    st.info("Aún no hay snapshots. Registra al menos uno.")
else:
    mins = [s["minute"] for s in snapshots]
    fig3 = go.Figure()
    fig3.add_trace(go.Scatter(x=mins, y=[(s["home_xg"] or 0.0) for s in snapshots],
                              mode="lines+markers", name="xG local"))
    fig3.add_trace(go.Scatter(x=mins, y=[(s["away_xg"] or 0.0) for s in snapshots],
                              mode="lines+markers", name="xG visita"))
    fig3.update_layout(xaxis_title="Minuto", yaxis_title="xG acumulado")
    st.plotly_chart(fig3, use_container_width=True)

# 4. Edge en el tiempo (de snapshots), con línea de referencia en 0.
st.markdown("**4. Edge en el tiempo**")
if not snapshots:
    st.info("Aún no hay snapshots. Registra al menos uno.")
else:
    mins = [s["minute"] for s in snapshots]
    fig4 = go.Figure()
    fig4.add_trace(go.Scatter(x=mins, y=[s["edge"] for s in snapshots],
                              mode="lines+markers", name="Edge"))
    fig4.add_hline(y=0.0, line_dash="dash", line_color="gray")
    fig4.update_layout(xaxis_title="Minuto", yaxis_title="Edge (modelo - mercado)")
    st.plotly_chart(fig4, use_container_width=True)
