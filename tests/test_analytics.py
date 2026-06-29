"""Tests de la analitica pura (spec de diseno, seccion 6.2).

Usa una calibracion realista (Argentina vs Cabo Verde, 0.86/0.11/0.04) para
construir una matriz de marcadores, y verifica las derivaciones del catalogo.
"""
import inspect

import pytest

from src.models import analytics, calibration, dixon_coles, poisson
from src.utils.config import load_config


@pytest.fixture(scope="module")
def cfg():
    return load_config()


@pytest.fixture(scope="module")
def calibrated(cfg):
    """Lambdas y matriz Dixon-Coles para Argentina (favorito) vs Cabo Verde."""
    target = calibration.normalize_prices(0.86, 0.11, 0.04)
    result = calibration.calibrate(target, model="dixon_coles", config=cfg)
    lh = result["lambda_home"]
    la = result["lambda_away"]
    rho = result["rho"]
    matrix = dixon_coles.score_matrix(lh, la, rho, cfg["max_goals"])
    return {"lambda_home": lh, "lambda_away": la, "rho": rho, "matrix": matrix}


def test_analytics_does_not_import_streamlit_or_connector():
    """analytics.py debe permanecer puro y desacoplado (sin imports prohibidos)."""
    import ast

    src = inspect.getsource(analytics)
    tree = ast.parse(src)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported.add(node.module.split(".")[0])
                # Detecta cosas como `from src.connectors import ...`.
                imported.add(node.module)
    assert "streamlit" not in imported
    assert not any("connector" in mod for mod in imported)
    assert not any("polymarket" in mod for mod in imported)


def test_expected_goals(calibrated):
    eg = analytics.expected_goals(calibrated["lambda_home"], calibrated["lambda_away"])
    assert eg["home"] == calibrated["lambda_home"]
    assert eg["away"] == calibrated["lambda_away"]
    assert abs(eg["total"] - (eg["home"] + eg["away"])) < 1e-12


def test_one_x_two_sums_to_one(calibrated):
    probs = analytics.one_x_two(calibrated["matrix"])
    assert abs(sum(probs.values()) - 1.0) < 1e-9


def test_total_goals_distribution_sums_to_one(calibrated):
    dist = analytics.total_goals_distribution(calibrated["matrix"], up_to=5)
    assert set(dist.keys()) == {0, 1, 2, 3, 4, "5+"}
    assert abs(sum(dist.values()) - 1.0) < 1e-9


def test_first_to_score(calibrated):
    """Favorito local fuerte: none = exp(-(lh+la)), los tres suman 1."""
    lh = calibrated["lambda_home"]
    la = calibrated["lambda_away"]
    fts = analytics.first_to_score(lh, la)
    import math
    assert abs(fts["none"] - math.exp(-(lh + la))) < 1e-12
    assert abs(sum(fts.values()) - 1.0) < 1e-9
    # Local mucho mas fuerte -> mas probable que anote primero que la visita.
    assert fts["home"] > fts["away"]


def test_clean_sheets_directional(calibrated):
    """Local fuerte -> visita rara vez anota -> valla invicta del LOCAL alta."""
    cs = analytics.clean_sheets(calibrated["matrix"])
    assert cs["home"] > cs["away"]


def test_over_under_monotonic(calibrated):
    matrix = calibrated["matrix"]
    o05 = analytics.over_under(matrix, 0.5)["over"]
    o15 = analytics.over_under(matrix, 1.5)["over"]
    o25 = analytics.over_under(matrix, 2.5)["over"]
    o35 = analytics.over_under(matrix, 3.5)["over"]
    assert o05 > o15 > o25 > o35
    # Over 2.5 debe coincidir con prob_total_goals_at_least(matrix, 3).
    assert abs(o25 - poisson.prob_total_goals_at_least(matrix, 3)) < 1e-12


def test_over_under_sums_to_one(calibrated):
    for line in (0.5, 1.5, 2.5, 3.5, 4.5):
        ou = analytics.over_under(calibrated["matrix"], line)
        assert abs(ou["over"] + ou["under"] - 1.0) < 1e-9


def test_btts_sums_to_one(calibrated):
    b = analytics.btts(calibrated["matrix"])
    assert abs(b["yes"] + b["no"] - 1.0) < 1e-9


def test_double_chance_consistency(calibrated):
    probs = analytics.one_x_two(calibrated["matrix"])
    dc = analytics.double_chance(probs)
    assert abs(dc["home_or_draw"] - (probs["home"] + probs["draw"])) < 1e-12
    assert abs(dc["home_or_away"] - (probs["home"] + probs["away"])) < 1e-12
    assert abs(dc["draw_or_away"] - (probs["draw"] + probs["away"])) < 1e-12


def test_winning_margin_sums_to_one(calibrated):
    margin = analytics.winning_margin(calibrated["matrix"])
    assert abs(sum(margin.values()) - 1.0) < 1e-9


def test_winning_margin_consistent_with_1x2(calibrated):
    """home_by_* suma = P(home); away_by_* suma = P(away); draw = P(draw)."""
    matrix = calibrated["matrix"]
    margin = analytics.winning_margin(matrix)
    probs = analytics.one_x_two(matrix)
    home_total = margin["home_by_1"] + margin["home_by_2"] + margin["home_by_3+"]
    away_total = margin["away_by_1"] + margin["away_by_2"] + margin["away_by_3+"]
    assert abs(home_total - probs["home"]) < 1e-9
    assert abs(away_total - probs["away"]) < 1e-9
    assert abs(margin["draw"] - probs["draw"]) < 1e-9


def test_top_scores(calibrated):
    scores = analytics.top_scores(calibrated["matrix"], n=5)
    assert len(scores) == 5
    # Ordenados de mas a menos probable.
    probs = [p for (_, _, p) in scores]
    assert probs == sorted(probs, reverse=True)


def test_model_vs_market_edge_and_sorting(calibrated):
    matrix = calibrated["matrix"]
    lh = calibrated["lambda_home"]
    la = calibrated["lambda_away"]
    quotes = [
        {"market": "draw", "market_price": 0.10},
        {"market": "over_2.5", "market_price": 0.40},
        {"market": "btts", "market_price": 0.50},
    ]
    rows = analytics.model_vs_market(matrix, lh, la, quotes)
    assert len(rows) == 3
    # edge = model_prob - market_price para cada fila.
    for row in rows:
        assert row["edge"] == row["model_prob"] - row["market_price"]
    # Coherencia de los valores del modelo.
    by_market = {r["market"]: r for r in rows}
    assert by_market["draw"]["model_prob"] == analytics.one_x_two(matrix)["draw"]
    assert by_market["over_2.5"]["model_prob"] == analytics.over_under(matrix, 2.5)["over"]
    assert by_market["btts"]["model_prob"] == analytics.btts(matrix)["yes"]
    # Ordenado por |edge| descendente.
    abs_edges = [abs(r["edge"]) for r in rows]
    assert abs_edges == sorted(abs_edges, reverse=True)


def test_model_vs_market_skips_unknown_market(calibrated):
    matrix = calibrated["matrix"]
    quotes = [
        {"market": "home", "market_price": 0.80},
        {"market": "corners_over_9.5", "market_price": 0.50},
    ]
    rows = analytics.model_vs_market(matrix, 1.0, 1.0, quotes)
    by_market = {r["market"]: r for r in rows}
    assert by_market["home"]["model_prob"] is not None
    assert by_market["corners_over_9.5"]["model_prob"] is None
    assert by_market["corners_over_9.5"]["edge"] is None
