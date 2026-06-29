"""Tests de Poisson y Dixon-Coles (spec maestro seccion 20.1)."""
import numpy as np
import pytest

from src.models import poisson, dixon_coles


def test_score_matrix_sums_to_one():
    m = poisson.score_matrix(1.7, 1.0)
    assert m.shape == (13, 13)
    assert abs(m.sum() - 1.0) < 1e-6


def test_outcome_probs_sum_to_one():
    m = poisson.score_matrix(1.7, 1.0)
    probs = poisson.outcome_probs(m)
    assert set(probs.keys()) == {"home", "draw", "away"}
    assert abs(probs["home"] + probs["draw"] + probs["away"] - 1.0) < 1e-6


def test_higher_lambda_home_wins_more():
    m = poisson.score_matrix(2.5, 0.8)
    probs = poisson.outcome_probs(m)
    assert probs["home"] > probs["away"]


def test_equal_lambdas_symmetric():
    m = poisson.score_matrix(1.4, 1.4)
    probs = poisson.outcome_probs(m)
    assert abs(probs["home"] - probs["away"]) < 1e-9


def test_top_scores_returns_sorted():
    m = poisson.score_matrix(1.5, 1.1)
    top = poisson.top_scores(m, n=5)
    assert len(top) == 5
    probs = [p for (_, _, p) in top]
    assert probs == sorted(probs, reverse=True)


def test_prob_total_goals_at_least():
    m = poisson.score_matrix(1.3, 1.2)
    p0 = poisson.prob_total_goals_at_least(m, 0)
    p3 = poisson.prob_total_goals_at_least(m, 3)
    assert abs(p0 - 1.0) < 1e-6
    assert 0.0 < p3 < 1.0
    # Monotono no creciente en k.
    assert poisson.prob_total_goals_at_least(m, 4) <= p3


# --- Dixon-Coles ---

def test_dixon_coles_sums_to_one():
    m = dixon_coles.score_matrix(1.7, 1.0, rho=-0.13)
    assert abs(m.sum() - 1.0) < 1e-6


def test_dixon_coles_increases_draw_low_scores():
    """rho negativo aumenta la masa de empates bajos vs Poisson puro."""
    lam_h, lam_a = 1.3, 1.1
    m_pois = poisson.score_matrix(lam_h, lam_a)
    m_dc = dixon_coles.score_matrix(lam_h, lam_a, rho=-0.13)
    p_draw_pois = poisson.outcome_probs(m_pois)["draw"]
    p_draw_dc = poisson.outcome_probs(m_dc)["draw"]
    assert p_draw_dc > p_draw_pois


def test_dixon_coles_zero_rho_equals_poisson():
    lam_h, lam_a = 1.6, 0.9
    m_pois = poisson.score_matrix(lam_h, lam_a)
    m_dc = dixon_coles.score_matrix(lam_h, lam_a, rho=0.0)
    assert np.allclose(m_pois, m_dc, atol=1e-9)
