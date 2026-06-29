"""Market Setup: precios → calibrar → outputs.

Página delgada: lee inputs, llama al motor (calibration) y a state, y renderiza.
Nada de matemática inline (vive en src/models/* y src/dashboard/*).
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

from src.dashboard import state
from src.models import calibration, dixon_coles, poisson
from src.utils.config import load_config
from src.utils.validation import calibration_warnings

st.set_page_config(page_title="Market Setup", page_icon="🎯")

cfg = load_config()

st.title("🎯 Market Setup")
st.caption("Ingresa precios, elige modelo y calibra los lambdas del partido.")

# --- Inputs: partido y equipos --------------------------------------------
st.subheader("Partido")
match_name = st.text_input(
    "Nombre del partido", value="Argentina vs Cabo Verde", key="setup_match_name"
)
col_a, col_b = st.columns(2)
with col_a:
    home_team = st.text_input(
        "Equipo A (local / favorito)", value="Argentina", key="setup_home_team"
    )
with col_b:
    away_team = st.text_input(
        "Equipo B (visita)", value="Cabo Verde", key="setup_away_team"
    )

# --- Inputs: precios -------------------------------------------------------
st.subheader("Precios de mercado (1X2)")
col1, col2, col3 = st.columns(3)
with col1:
    price_home = st.number_input(
        "Precio A (local)", min_value=0.0, max_value=1.0, value=0.86,
        step=0.01, format="%.4f", key="setup_price_home",
    )
with col2:
    price_draw = st.number_input(
        "Precio empate", min_value=0.0, max_value=1.0, value=0.11,
        step=0.01, format="%.4f", key="setup_price_draw",
    )
with col3:
    price_away = st.number_input(
        "Precio B (visita)", min_value=0.0, max_value=1.0, value=0.04,
        step=0.01, format="%.4f", key="setup_price_away",
    )

use_over = st.checkbox(
    "Incluir precio Over 2.5 (libera ρ en Dixon-Coles)",
    value=False, key="setup_use_over",
)
over_price = None
if use_over:
    over_price = st.number_input(
        "Precio Over 2.5", min_value=0.0, max_value=1.0, value=0.50,
        step=0.01, format="%.4f", key="setup_over_price",
    )

# --- Inputs: modelo --------------------------------------------------------
model_label = st.radio(
    "Modelo",
    options=["Poisson", "Dixon-Coles"],
    horizontal=True,
    key="setup_model_label",
)
model_type = "dixon_coles" if model_label == "Dixon-Coles" else "poisson"

# --- Inputs opcionales (display-only, no entran al cálculo) ----------------
with st.expander("Contexto del mercado (opcional, solo se guarda)"):
    oc1, oc2 = st.columns(2)
    with oc1:
        best_bid = st.number_input(
            "Best bid (empate)", min_value=0.0, max_value=1.0, value=0.0,
            step=0.01, format="%.4f", key="setup_best_bid",
        )
        volume = st.number_input(
            "Volumen", min_value=0.0, value=0.0, step=1.0, key="setup_volume",
        )
        start_time = st.text_input(
            "Hora de inicio", value="", key="setup_start_time"
        )
    with oc2:
        best_ask = st.number_input(
            "Best ask (empate)", min_value=0.0, max_value=1.0, value=0.0,
            step=0.01, format="%.4f", key="setup_best_ask",
        )
        liquidity = st.number_input(
            "Liquidez", min_value=0.0, value=0.0, step=1.0, key="setup_liquidity",
        )

# --- Acción: Calibrar ------------------------------------------------------
if st.button("Calibrar", type="primary", key="setup_calibrate_btn"):
    normalized = calibration.normalize_prices(price_home, price_draw, price_away)
    result = calibration.calibrate(
        normalized,
        model=model_type,
        over_2_5_price=over_price if use_over else None,
        config=cfg,
    )
    metadata = {
        "home_team": home_team,
        "away_team": away_team,
        "match_name": match_name,
        "model_type": model_type,
        "best_bid": best_bid,
        "best_ask": best_ask,
        "volume": volume,
        "liquidity": liquidity,
        "start_time": start_time,
    }
    state.save_model(
        metadata=metadata,
        calibration_result=result,
        market_probs=normalized,
        config=cfg,
    )
    # Limpiar snapshots viejos del partido anterior.
    state.clear_snapshots()
    st.success("Modelo calibrado y guardado en la sesión.")

# --- Outputs (si hay modelo) ----------------------------------------------
model = state.get_model()
if model is None:
    st.info("Calibra para ver los resultados.")
    st.stop()

st.divider()
st.subheader("Resultados de calibración")

market = model["market_probs"]
lambda_home = model["lambda_home"]
lambda_away = model["lambda_away"]
rho = model["rho"]

# Probabilidades normalizadas del mercado.
oc1, oc2, oc3 = st.columns(3)
oc1.metric("Mercado P(local)", f"{market['home']:.3f}")
oc2.metric("Mercado P(empate)", f"{market['draw']:.3f}")
oc3.metric("Mercado P(visita)", f"{market['away']:.3f}")

# Lambdas / rho.
lc1, lc2, lc3 = st.columns(3)
lc1.metric("λ local", f"{lambda_home:.3f}")
lc2.metric("λ visita", f"{lambda_away:.3f}")
lc3.metric("ρ", f"{rho:.3f}")

# Matriz del modelo según el tipo elegido.
max_goals = cfg["max_goals"]
if model["model_type"] == "dixon_coles":
    matrix = dixon_coles.score_matrix(lambda_home, lambda_away, rho, max_goals)
else:
    matrix = poisson.score_matrix(lambda_home, lambda_away, max_goals)

model_probs = poisson.outcome_probs(matrix)

# Advertencias: |modelo - mercado| > 0.03 en algún outcome.
warnings = calibration_warnings(model_probs, market)
if warnings:
    for w in warnings:
        st.warning(w)
else:
    st.caption("Sin advertencias: el modelo reproduce bien el mercado.")

# Top 10 marcadores.
st.subheader("Marcadores más probables (top 10)")
top = poisson.top_scores(matrix, 10)
top_rows = [
    {"Marcador": f"{h}-{a}", "Probabilidad": f"{p:.3f}"} for h, a, p in top
]
st.table(top_rows)

# Over 2.5 del modelo.
over_model = poisson.prob_total_goals_at_least(matrix, 3)
st.metric("Over 2.5 (modelo)", f"{over_model:.3f}")

# Comparación modelo vs mercado 1X2 (tabla + barras).
st.subheader("Modelo vs mercado (1X2)")
comp_rows = [
    {"Outcome": "Local", "Modelo": f"{model_probs['home']:.3f}", "Mercado": f"{market['home']:.3f}"},
    {"Outcome": "Empate", "Modelo": f"{model_probs['draw']:.3f}", "Mercado": f"{market['draw']:.3f}"},
    {"Outcome": "Visita", "Modelo": f"{model_probs['away']:.3f}", "Mercado": f"{market['away']:.3f}"},
]
st.table(comp_rows)

labels = ["Local", "Empate", "Visita"]
fig = go.Figure()
fig.add_trace(go.Bar(
    name="Modelo", x=labels,
    y=[model_probs["home"], model_probs["draw"], model_probs["away"]],
))
fig.add_trace(go.Bar(
    name="Mercado", x=labels,
    y=[market["home"], market["draw"], market["away"]],
))
fig.update_layout(barmode="group", yaxis_title="Probabilidad", legend_title="")
st.plotly_chart(fig, use_container_width=True)
