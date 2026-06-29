"""Home del dashboard: estado del modelo + instrucciones del flujo.

Entrypoint de la app multipágina de Streamlit. Se ejecuta con:
    streamlit run app/dashboard.py

Las páginas viven en app/pages/ y comparten estado vía st.session_state
(envuelto en src/dashboard/state.py).
"""
import os
import sys

# --- bootstrap de sys.path -------------------------------------------------
# Bajo `streamlit run`, el dir del script (app/) queda en sys.path, no la raíz
# del proyecto. Insertamos la raíz para que `from src...` resuelva.
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import streamlit as st

from src.dashboard import state

st.set_page_config(page_title="Dashboard fútbol — Home", page_icon="⚽")

st.title("⚽ Dashboard manual de probabilidades")

st.markdown(
    """
Esta app envuelve el motor de probabilidades en una UI manual. El flujo tiene
dos pasos:

1. **Market Setup** — ingresas los precios 1X2 (y opcionalmente Over 2.5),
   eliges el modelo (Poisson o Dixon-Coles) y **calibras**. Eso fija los
   *lambdas* del partido.
2. **Live Match** — con el modelo ya calibrado, ingresas el estado del partido
   a mano (minuto, marcador, xG, tarjetas) y ves las probabilidades live, el
   precio justo del empate, el *edge* contra el mercado y gráficos de la serie
   de snapshots que vas registrando.

Usa el menú lateral para navegar entre páginas.
"""
)

st.divider()

st.subheader("Estado del modelo")

model = state.get_model()
if model is None:
    st.info(
        "Aún no hay un modelo calibrado. Ve a **Market Setup** para ingresar "
        "precios y calibrar."
    )
else:
    meta = model["metadata"]
    st.success(f"Modelo calibrado: **{meta.get('match_name', '(sin nombre)')}**")
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Local (favorito)", meta.get("home_team", "—"))
        st.metric("λ local", f"{model['lambda_home']:.3f}")
    with col2:
        st.metric("Visita", meta.get("away_team", "—"))
        st.metric("λ visita", f"{model['lambda_away']:.3f}")
    st.caption(
        f"Modelo: **{model['model_type']}**  ·  ρ = {model['rho']:.3f}"
    )

st.divider()

if st.button("🔄 Reiniciar sesión", key="reset_session_btn"):
    state.reset_session()
    st.success("Sesión reiniciada. Vuelve a Market Setup para calibrar.")
