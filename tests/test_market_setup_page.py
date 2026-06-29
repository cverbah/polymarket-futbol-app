"""AppTest de la pagina Market Setup reescrita (spec seccion 6.3).

Sin red: se parsea la lista de partidos y los mercados del partido desde los
fixtures JSON reales usando las funciones de parsing puras del connector, y se
mockean las funciones de alto nivel `pm.list_world_cup_matches` /
`pm.get_match_markets` con esos objetos. Se limpia el cache de Streamlit antes de
correr para que los wrappers cacheados no opaquen el patch.
"""
import json
import os
from unittest.mock import patch

import streamlit as st
from streamlit.testing.v1 import AppTest

from src.connectors import polymarket as pm
from src.dashboard import state

SETUP = "app/pages/01_market_setup.py"
_FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
_PM_CONFIG = {"max_spread": 0.06, "min_liquidity": 500}


def _load(name: str):
    with open(os.path.join(_FIXTURES, name), "r") as f:
        return json.load(f)


def _match_list():
    return pm.parse_match_list(_load("wc_events_list.json"), "fifwc-")


def _germany_paraguay_markets():
    main = _load("wc_match_main.json")[0]
    more = _load("wc_match_more_markets.json")[0]
    return pm.parse_match_markets(main, more, _PM_CONFIG)


def _run_patched():
    """Corre la pagina con las funciones de red parcheadas (sin red)."""
    st.cache_data.clear()  # evita que los wrappers cacheados opaquen el patch
    matches = _match_list()
    markets = _germany_paraguay_markets()
    with patch.object(pm, "list_world_cup_matches", return_value=matches), \
            patch.object(pm, "get_match_markets", return_value=markets):
        at = AppTest.from_file(SETUP)
        at.default_timeout = 30
        at.run()
        return at, matches, markets


def test_page_runs_without_exception():
    at, _, _ = _run_patched()
    assert not at.exception


def test_selecting_match_saves_compatible_model_and_renders_mvm():
    at, matches, markets = _run_patched()
    assert not at.exception

    # Selecciona Germany vs Paraguay (slug del fixture) y vuelve a correr.
    target = next(m for m in matches if m.slug == "fifwc-ger-par-2026-06-29")
    at.selectbox(key="setup_match_select").set_value(target).run()
    assert not at.exception

    # session_state contiene un modelo con forma compatible con Live Match.
    model = at.session_state[state.MODEL_KEY]
    assert model is not None
    assert "lambda_home" in model and model["lambda_home"] > 0
    assert "lambda_away" in model and model["lambda_away"] > 0
    assert "rho" in model
    assert model["model_type"] in ("dixon_coles", "poisson")
    assert model["metadata"]["home_team"] == "Germany"
    assert model["metadata"]["away_team"] == "Paraguay"
    assert model["metadata"]["match_name"] == "Germany vs Paraguay"
    # Favorito fuerte: Germany (precio ~0.715) => lambda local > visita.
    assert model["lambda_home"] > model["lambda_away"]

    # La seccion Modelo vs Mercado se renderizo (dataframe presente).
    assert len(at.dataframe) >= 1


def test_default_model_is_dixon_coles():
    at, _, _ = _run_patched()
    assert not at.exception
    # El radio default es Dixon-Coles -> el modelo guardado es dixon_coles.
    model = at.session_state[state.MODEL_KEY]
    assert model["model_type"] == "dixon_coles"
