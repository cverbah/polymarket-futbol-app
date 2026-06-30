"""AppTest de la página Live Match auto-refrescada.

Sin red: se parsea un MatchMarkets desde fixtures reales y se mockea
pm.get_match_markets. El modelo se pre-siembra en session_state como lo haría
Market Setup. Cada at.run() ejecuta el fragmento una vez (simula un 'tick').
"""
import json
import os
from unittest.mock import patch

import streamlit as st
from streamlit.testing.v1 import AppTest

from src.connectors import polymarket as pm
from src.dashboard import state

LIVE = "app/pages/02_live_match.py"
_FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
_PM_CONFIG = {"max_spread": 0.06, "min_liquidity": 500}


def _load(name):
    with open(os.path.join(_FIXTURES, name), "r") as f:
        return json.load(f)


def _markets(main_name, more_name=None):
    main = _load(main_name)[0]
    more = _load(more_name)[0] if more_name else None
    return pm.parse_match_markets(main, more, _PM_CONFIG)


def _model(slug="fifwc-ger-par"):
    return {
        "metadata": {
            "home_team": "Germany", "away_team": "Paraguay",
            "match_name": "Germany vs Paraguay", "model_type": "poisson",
            "slug": slug,
        },
        "model_type": "poisson",
        "lambda_home": 1.6, "lambda_away": 1.0, "rho": -0.13,
        "market_probs": {"home": 0.5, "draw": 0.3, "away": 0.2},
        "config": {},
    }


def _all_text(at):
    chunks = []
    for coll in (at.markdown, at.caption, at.success, at.info, at.warning, at.error, at.subheader):
        for el in coll:
            chunks.append(str(getattr(el, "value", "")))
    return "\n".join(chunks)


def test_live_without_model_shows_warning():
    st.cache_data.clear()
    at = AppTest.from_file(LIVE).run()
    assert not at.exception
    assert any("Calibra primero" in w.value for w in at.warning)


def test_live_renders_scoreboard_kpis_and_charts():
    st.cache_data.clear()
    markets = _markets("wc_match_main.json", "wc_match_more_markets.json")  # LIVE 0-0 min 13
    with patch.object(pm, "get_match_markets", return_value=markets):
        at = AppTest.from_file(LIVE)
        at.default_timeout = 30
        at.session_state[state.MODEL_KEY] = _model()
        at.run()
        assert not at.exception

        text = _all_text(at)
        assert "EN VIVO" in text
        assert "13" in text  # minuto del fixture

        labels = [str(getattr(m, "label", "")) for m in at.metric]
        assert any("P(gana Germany)" in l for l in labels)
        assert any("P(empate)" in l for l in labels)
        assert any("P(gana Paraguay)" in l for l in labels)

        # AppTest no expone plotly_chart directamente; verificamos indirectamente
        # que hay datos en la serie (lo que activa la rama de renderizado de gráficos).
        # Nota: at.session_state no soporta .get(); se usa subscript con try/except.
        try:
            series = at.session_state[state.SERIES_KEY]
        except KeyError:
            series = []
        assert len(series) >= 1


def test_live_accumulates_and_marks_goal():
    st.cache_data.clear()
    m_00 = _markets("wc_match_main.json", "wc_match_more_markets.json")   # 0-0 min 13
    m_11 = _markets("wc_match_live_scored.json")                          # 1-1 min 70
    with patch.object(pm, "get_match_markets") as mock_get:
        at = AppTest.from_file(LIVE)
        at.default_timeout = 30
        at.session_state[state.MODEL_KEY] = _model()

        mock_get.return_value = m_00
        at.run()
        mock_get.return_value = m_11
        at.run()

        try:
            series = at.session_state[state.SERIES_KEY]
        except KeyError:
            series = []
        assert len(series) == 2
        assert (series[-1]["home_score"], series[-1]["away_score"]) == (1, 1)


def test_live_series_resets_on_match_change():
    st.cache_data.clear()
    markets = _markets("wc_match_main.json", "wc_match_more_markets.json")
    with patch.object(pm, "get_match_markets", return_value=markets):
        at = AppTest.from_file(LIVE)
        at.default_timeout = 30
        at.session_state[state.MODEL_KEY] = _model(slug="fifwc-aaa")
        at.run()
        try:
            series_aaa = at.session_state[state.SERIES_KEY]
        except KeyError:
            series_aaa = []
        assert len(series_aaa) == 1

        at.session_state[state.MODEL_KEY] = _model(slug="fifwc-bbb")
        at.run()
        try:
            series_bbb = at.session_state[state.SERIES_KEY]
        except KeyError:
            series_bbb = []
        assert len(series_bbb) == 1  # no acumuló sobre el anterior


def test_live_post_shows_final_and_stops_accumulating():
    st.cache_data.clear()
    markets = _markets("wc_match_post.json")  # VFT 2-1
    with patch.object(pm, "get_match_markets", return_value=markets):
        at = AppTest.from_file(LIVE)
        at.default_timeout = 30
        at.session_state[state.MODEL_KEY] = _model()
        at.run()
        assert not at.exception

        text = _all_text(at)
        assert "Finalizado" in text
        assert "2 – 1" in text
        try:
            series_post = at.session_state[state.SERIES_KEY]
        except KeyError:
            series_post = []
        assert len(series_post) == 0


def test_live_pre_shows_waiting_and_no_accumulation():
    st.cache_data.clear()
    markets = _markets("wc_match_pre.json")
    with patch.object(pm, "get_match_markets", return_value=markets):
        at = AppTest.from_file(LIVE)
        at.default_timeout = 30
        at.session_state[state.MODEL_KEY] = _model()
        at.run()
        assert not at.exception
        text = _all_text(at)
        assert "Aún no comienza" in text
        # at.session_state no soporta .get(); se usa subscript con try/except.
        try:
            series_pre = at.session_state[state.SERIES_KEY]
        except KeyError:
            series_pre = []
        assert len(series_pre) == 0
