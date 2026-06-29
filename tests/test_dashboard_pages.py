"""AppTest sobre las páginas del dashboard (spec sección 6.2).

Usa streamlit.testing.v1.AppTest para bootear cada página sin un navegador.
AppTest preserva session_state entre llamadas a at.run() dentro del mismo
objeto, así que podemos simular el flujo Setup -> (estado) -> Live.
"""
import json
import os
from unittest.mock import patch

import streamlit as st
from streamlit.testing.v1 import AppTest

from src.connectors import polymarket as pm
from src.dashboard import state

_FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
_PM_CONFIG = {"max_spread": 0.06, "min_liquidity": 500}


def _load_fixture(name: str):
    with open(os.path.join(_FIXTURES, name), "r") as f:
        return json.load(f)

HOME = "app/dashboard.py"
SETUP = "app/pages/01_market_setup.py"
LIVE = "app/pages/02_live_match.py"


def _valid_model():
    """Dict MODEL válido con la misma forma que guarda state.save_model."""
    return {
        "metadata": {
            "home_team": "Argentina",
            "away_team": "Cabo Verde",
            "match_name": "Argentina vs Cabo Verde",
            "model_type": "poisson",
        },
        "model_type": "poisson",
        "lambda_home": 2.5,
        "lambda_away": 0.4,
        "rho": -0.13,
        "market_probs": {"home": 0.85, "draw": 0.11, "away": 0.04},
        "config": {},
    }


# --- Home ------------------------------------------------------------------

def test_home_runs_without_exception():
    at = AppTest.from_file(HOME).run()
    assert not at.exception


# --- Market Setup ----------------------------------------------------------

def test_market_setup_calibrates_and_saves_model():
    # La pagina reescrita lee precios desde Polymarket; sin red, parcheamos las
    # funciones de alto nivel con objetos parseados de los fixtures.
    st.cache_data.clear()
    matches = pm.parse_match_list(_load_fixture("wc_events_list.json"), "fifwc-")
    markets = pm.parse_match_markets(
        _load_fixture("wc_match_main.json")[0],
        _load_fixture("wc_match_more_markets.json")[0],
        _PM_CONFIG,
    )
    with patch.object(pm, "list_world_cup_matches", return_value=matches), \
            patch.object(pm, "get_match_markets", return_value=markets):
        at = AppTest.from_file(SETUP)
        at.default_timeout = 30
        at.run()
        assert not at.exception

        # session_state debe tener un modelo con lambdas plausibles.
        model = at.session_state[state.MODEL_KEY]
        assert model is not None
        assert model["metadata"]["home_team"] == "Germany"
        assert model["model_type"] == "dixon_coles"
        # Favorito fuerte (Germany ~0.715): lambda local > lambda visita.
        assert model["lambda_home"] > model["lambda_away"]
        assert model["lambda_home"] > 0
        assert model["lambda_away"] > 0


# --- Live sin modelo -------------------------------------------------------

def test_live_without_model_shows_warning():
    at = AppTest.from_file(LIVE).run()
    assert not at.exception
    # Debe mostrar el aviso y detenerse limpiamente (st.stop()).
    assert any("Calibra primero" in w.value for w in at.warning)


# --- Live con modelo -------------------------------------------------------

def test_live_with_model_registers_snapshot():
    at = AppTest.from_file(LIVE)
    at.default_timeout = 30
    # Pre-sembrar el modelo igual que lo hace state.save_model.
    at.session_state[state.MODEL_KEY] = _valid_model()
    at.run()
    assert not at.exception

    # Setear inputs live.
    at.number_input(key="live_minute").set_value(30)
    at.number_input(key="live_home_score").set_value(0)
    at.number_input(key="live_away_score").set_value(0)
    at.number_input(key="live_market_draw").set_value(0.18)
    at.run()
    assert not at.exception

    # Registrar snapshot.
    at.button(key="live_register_btn").click().run()
    assert not at.exception

    snapshots = at.session_state[state.SNAPSHOTS_KEY]
    assert len(snapshots) == 1
    assert snapshots[0]["minute"] == 30
