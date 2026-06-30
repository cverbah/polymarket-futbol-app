"""Tests de la lógica pura del dashboard (spec sección 6.1).

logic.py NO importa streamlit; estos tests tampoco, para mantenerlo puro y
unit-testeable sin una app de Streamlit corriendo.

state.py depende de st.session_state y se cubre con los AppTest de las páginas
(otra tarea); no se testea aquí para no requerir una app corriendo.
"""
import json
import os

import pytest

from src.connectors import polymarket as pm
from src.dashboard import logic

from src.utils.config import load_config

CFG = load_config()

_FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
_PM_CONFIG = {"max_spread": 0.06, "min_liquidity": 500}


def _load_fix(name):
    with open(os.path.join(_FIXTURES, name), "r") as f:
        return json.load(f)


def _live_markets():
    """Germany vs Paraguay LIVE 0-0 (1H, min 13) con O/U + BTTS."""
    main = _load_fix("wc_match_main.json")[0]
    more = _load_fix("wc_match_more_markets.json")[0]
    return pm.parse_match_markets(main, more, _PM_CONFIG)


def _live_model():
    return {
        "model_type": "poisson",
        "lambda_home": 1.6,
        "lambda_away": 1.0,
        "rho": -0.13,
        "metadata": {"slug": "fifwc-ger-par"},
    }


# --- compute_edge ---

def test_compute_edge_sign_and_magnitude():
    assert logic.compute_edge(0.30, 0.25) == pytest.approx(0.05)
    assert logic.compute_edge(0.20, 0.25) == pytest.approx(-0.05)
    assert logic.compute_edge(0.25, 0.25) == pytest.approx(0.0)


# --- describe_edge ---

def test_describe_edge_positive():
    label = logic.describe_edge(0.042)
    assert "+4.2" in label
    assert "empate" in label


def test_describe_edge_negative():
    label = logic.describe_edge(-0.015)
    assert "-1.5" in label
    assert "empate" in label


def test_describe_edge_within_tolerance():
    # |edge| < tol (0.005) -> coinciden
    assert logic.describe_edge(0.001) == "Modelo y mercado coinciden en el empate"
    assert logic.describe_edge(-0.001) == "Modelo y mercado coinciden en el empate"
    assert logic.describe_edge(0.0) == "Modelo y mercado coinciden en el empate"


# --- build_live_snapshot ---

def test_build_live_snapshot_keys_and_consistency():
    snap = logic.build_live_snapshot(_live_model(), _live_markets(), CFG)

    expected = {
        "minute", "home_score", "away_score", "status",
        "model_home_prob", "model_draw_prob", "model_away_prob",
        "market_draw_price", "edge", "edges", "best_opportunity",
    }
    assert expected <= set(snap.keys())

    assert snap["status"] == "in"
    assert snap["home_score"] == 0 and snap["away_score"] == 0

    total = snap["model_home_prob"] + snap["model_draw_prob"] + snap["model_away_prob"]
    assert total == pytest.approx(1.0, abs=1e-6)

    assert snap["edge"] == pytest.approx(snap["model_draw_prob"] - snap["market_draw_price"])

    assert len(snap["edges"]) >= 3
    abs_edges = [abs(e["edge"]) for e in snap["edges"] if e["edge"] is not None]
    assert abs_edges == sorted(abs_edges, reverse=True)

    assert snap["best_opportunity"]["edge"] is not None


def test_goal_markers_detects_score_changes():
    series = [
        {"minute": 10, "home_score": 0, "away_score": 0},
        {"minute": 20, "home_score": 0, "away_score": 0},
        {"minute": 35, "home_score": 1, "away_score": 0},
        {"minute": 70, "home_score": 1, "away_score": 1},
    ]
    markers = logic.goal_markers(series)
    assert [m["minute"] for m in markers] == [35, 70]
    assert markers[0]["home_score"] == 1 and markers[0]["away_score"] == 0


def test_goal_markers_empty_and_single():
    assert logic.goal_markers([]) == []
    assert logic.goal_markers([{"minute": 5, "home_score": 0, "away_score": 0}]) == []


def test_market_label():
    assert logic.market_label("draw") == "Empate"
    assert logic.market_label("home") == "Local"
    assert logic.market_label("away") == "Visita"
    assert logic.market_label("btts") == "BTTS"
    assert logic.market_label("over_2.5") == "Over 2.5"
    assert logic.market_label("desconocido") == "desconocido"
