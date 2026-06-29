"""Tests del motor live (spec maestro secciones 9-11, 20.2, 20.3)."""
import pytest

from src.models import live_update, poisson
from src.models.live_update import MatchState
from src.utils.config import load_config

CFG = load_config()

# Ejemplo Argentina vs Cabo Verde calibrado (~2.76 / 0.46).
LAM_H, LAM_A = 2.76, 0.46


# --- Live outcome probs ---

def test_minute_0_matches_prematch():
    """Al minuto 0 con 0-0 y sin xG, las probabilidades ~ pre-partido."""
    pre = poisson.outcome_probs(poisson.score_matrix(LAM_H, LAM_A))
    state = MatchState(minute=0, home_score=0, away_score=0)
    live = live_update.live_outcome_probs(LAM_H, LAM_A, state, CFG)
    for k in ("home", "draw", "away"):
        assert abs(live[k] - pre[k]) < 1e-6


def test_minute_90_level_score_draw_almost_one():
    state = MatchState(minute=90, home_score=1, away_score=1)
    live = live_update.live_outcome_probs(LAM_H, LAM_A, state, CFG)
    assert live["draw"] > 0.99


def test_minute_90_home_ahead_home_almost_one():
    state = MatchState(minute=90, home_score=2, away_score=0)
    live = live_update.live_outcome_probs(LAM_H, LAM_A, state, CFG)
    assert live["home"] > 0.99


def test_probs_sum_to_one_live():
    state = MatchState(minute=55, home_score=1, away_score=0)
    live = live_update.live_outcome_probs(LAM_H, LAM_A, state, CFG)
    assert abs(sum(live.values()) - 1.0) < 1e-6


# --- xG adjustment ---

def test_high_favorite_xg_raises_remaining_lambda():
    """Si el favorito genera mucho xG, su lambda restante sube vs base."""
    state = MatchState(minute=30, home_score=0, away_score=0, home_xg=2.5, away_xg=0.1)
    adj = live_update.adjusted_remaining_lambdas(LAM_H, LAM_A, state, CFG)
    base = LAM_H * (90 - 30) / 90
    assert adj["lambda_home"] > base


def test_low_favorite_xg_lowers_remaining_lambda():
    """Si el favorito genera poco xG, su lambda restante baja vs base."""
    state = MatchState(minute=30, home_score=0, away_score=0, home_xg=0.2, away_xg=0.1)
    adj = live_update.adjusted_remaining_lambdas(LAM_H, LAM_A, state, CFG)
    base = LAM_H * (90 - 30) / 90
    assert adj["lambda_home"] < base


def test_no_xg_uses_base():
    """Sin datos de xG, las lambdas restantes son las base."""
    state = MatchState(minute=45, home_score=0, away_score=0)
    adj = live_update.adjusted_remaining_lambdas(LAM_H, LAM_A, state, CFG)
    assert abs(adj["lambda_home"] - LAM_H * 0.5) < 1e-9
    assert abs(adj["lambda_away"] - LAM_A * 0.5) < 1e-9


def test_safety_caps_clip_extreme_xg():
    """xG absurdamente alto se recorta al cap maximo del base."""
    state = MatchState(minute=10, home_score=0, away_score=0, home_xg=10.0, away_xg=0.0)
    adj = live_update.adjusted_remaining_lambdas(LAM_H, LAM_A, state, CFG)
    base = LAM_H * (90 - 10) / 90
    assert adj["lambda_home"] <= CFG["lambda_cap_max_multiplier"] * base + 1e-9


def test_red_card_lowers_offending_team():
    """Roja al local baja su lambda y sube la del rival."""
    state = MatchState(minute=30, home_score=0, away_score=0, home_red_cards=1)
    adj = live_update.adjusted_remaining_lambdas(LAM_H, LAM_A, state, CFG)
    no_card = MatchState(minute=30, home_score=0, away_score=0)
    adj_base = live_update.adjusted_remaining_lambdas(LAM_H, LAM_A, no_card, CFG)
    assert adj["lambda_home"] < adj_base["lambda_home"]
    assert adj["lambda_away"] > adj_base["lambda_away"]


# --- Fair draw curve ---

def test_fair_draw_curve_rises_over_time():
    """Si sigue 0-0, P(empate) sube con el minuto."""
    curve = live_update.fair_draw_curve(LAM_H, LAM_A, CFG)
    draws = [point["p_draw"] for point in curve]
    # Monotono creciente (con tolerancia numerica minima).
    for earlier, later in zip(draws, draws[1:]):
        assert later >= earlier - 1e-9
    assert draws[-1] > draws[0]


def test_fair_draw_curve_favorite_falls():
    """Si sigue 0-0, P(favorito gana) baja con el minuto."""
    curve = live_update.fair_draw_curve(LAM_H, LAM_A, CFG)
    homes = [point["p_home"] for point in curve]
    assert homes[-1] < homes[0]


def test_fair_draw_curve_prob_0_0_final_rises():
    """P(0-0 final | sigue 0-0) sube con el minuto."""
    curve = live_update.fair_draw_curve(LAM_H, LAM_A, CFG)
    p00 = [point["p_0_0_final"] for point in curve]
    assert p00[-1] > p00[0]
