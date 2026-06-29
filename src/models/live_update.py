"""Motor live: lambdas restantes, ajuste por xG, eventos y curva del empate.

Pipeline (spec maestro secciones 9, 10, 11):
  1. remaining_fraction = max(0, 90 - minute) / 90  -> lambdas restantes base.
  2. Ajuste xG (si hay datos): ritmo full implicito + shrinkage contra el prior
     (w_live = minute / (minute + tau)) + momentum de los ultimos 10 min.
  3. Caps de seguridad: clip entre cap_min y cap_max multiplicadores del base.
  4. Eventos: multiplicadores por tarjeta roja.
  5. Probabilidades condicionadas al marcador actual: se modelan los goles
     RESTANTES y se suman al marcador actual (H, A).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from src.models import poisson, dixon_coles


@dataclass
class MatchState:
    minute: float
    home_score: int
    away_score: int
    home_xg: Optional[float] = None
    away_xg: Optional[float] = None
    home_xg_last_10: Optional[float] = None
    away_xg_last_10: Optional[float] = None
    home_red_cards: int = 0
    away_red_cards: int = 0


def _remaining_fraction(minute: float) -> float:
    return max(0.0, 90.0 - minute) / 90.0


def _adjust_one(lambda_init, xg, xg_last_10, minute, cfg):
    """Lambda full ajustado por xG para un equipo (shrinkage + momentum).

    Si no hay xG acumulado para el equipo, devuelve el prior sin cambios.
    """
    if xg is None:
        return lambda_init

    tau = cfg["tau_minutes"]
    recent_weight = cfg["recent_xg_weight"]
    window = cfg["recent_xg_window"]

    # Ritmo full implicito desde xG acumulado.
    pace_full = xg * 90.0 / max(minute, 1.0)

    # Shrinkage contra el prior: a mas minutos, mas peso al observado.
    w_live = minute / (minute + tau)
    lambda_adj = (1.0 - w_live) * lambda_init + w_live * pace_full

    # Momentum de los ultimos 10 min (si hay dato).
    if xg_last_10 is not None:
        recent_pace_full = xg_last_10 * 90.0 / window
        lambda_adj = (1.0 - recent_weight) * lambda_adj + recent_weight * recent_pace_full

    return lambda_adj


def adjusted_remaining_lambdas(lambda_home_init, lambda_away_init, state, config) -> dict:
    """Lambdas restantes ajustadas por xG, caps y eventos."""
    cfg = config
    minute = state.minute
    frac = _remaining_fraction(minute)

    # 1. Base restante.
    base_home = lambda_home_init * frac
    base_away = lambda_away_init * frac

    # 2. Ajuste por xG (lambda full ajustado -> restante).
    full_home = _adjust_one(lambda_home_init, state.home_xg, state.home_xg_last_10, minute, cfg)
    full_away = _adjust_one(lambda_away_init, state.away_xg, state.away_xg_last_10, minute, cfg)
    rem_home = full_home * frac
    rem_away = full_away * frac

    # 3. Caps de seguridad respecto al base.
    cap_min = cfg["lambda_cap_min_multiplier"]
    cap_max = cfg["lambda_cap_max_multiplier"]
    if base_home > 0:
        rem_home = float(np.clip(rem_home, cap_min * base_home, cap_max * base_home))
    if base_away > 0:
        rem_away = float(np.clip(rem_away, cap_min * base_away, cap_max * base_away))

    # 4. Eventos: tarjetas rojas (multiplicadores configurables).
    atk_mult = cfg["red_card_attack_multiplier"]
    opp_mult = cfg["red_card_opponent_multiplier"]
    for _ in range(state.home_red_cards):
        rem_home *= atk_mult
        rem_away *= opp_mult
    for _ in range(state.away_red_cards):
        rem_away *= atk_mult
        rem_home *= opp_mult

    return {"lambda_home": rem_home, "lambda_away": rem_away}


def _remaining_matrix(lambda_home, lambda_away, model, rho, max_goals):
    """Matriz de goles RESTANTES segun el modelo elegido."""
    if model == "dixon_coles":
        if rho is None:
            raise ValueError("Dixon-Coles requiere rho.")
        return dixon_coles.score_matrix(lambda_home, lambda_away, rho, max_goals)
    return poisson.score_matrix(lambda_home, lambda_away, max_goals)


def live_outcome_probs(lambda_home_init, lambda_away_init, state, config,
                       model="poisson", rho=None) -> dict:
    """Probabilidades 1X2 live condicionadas al marcador actual.

    Modela los goles restantes, los suma al marcador actual (H, A), y deriva
    P_home / P_draw / P_away sobre el marcador final.
    """
    max_goals = config["max_goals"]
    adj = adjusted_remaining_lambdas(lambda_home_init, lambda_away_init, state, config)
    matrix = _remaining_matrix(adj["lambda_home"], adj["lambda_away"], model, rho, max_goals)

    H, A = state.home_score, state.away_score
    home = draw = away = 0.0
    n_rows, n_cols = matrix.shape
    for i in range(n_rows):       # goles restantes home
        for j in range(n_cols):   # goles restantes away
            final_home = H + i
            final_away = A + j
            p = matrix[i, j]
            if final_home > final_away:
                home += p
            elif final_home == final_away:
                draw += p
            else:
                away += p
    return {"home": float(home), "draw": float(draw), "away": float(away)}


def fair_draw_curve(lambda_home_init, lambda_away_init, config,
                    model="poisson", rho=None, minutes=range(0, 91, 5)) -> list:
    """Curva de precio justo del empate asumiendo que el partido sigue 0-0.

    Para cada minuto devuelve un dict con p_home/p_draw/p_away y p_0_0_final
    (probabilidad de terminar exactamente 0-0 desde ese minuto).
    """
    max_goals = config["max_goals"]
    curve = []
    for m in minutes:
        state = MatchState(minute=m, home_score=0, away_score=0)
        probs = live_outcome_probs(lambda_home_init, lambda_away_init, state,
                                   config, model=model, rho=rho)
        adj = adjusted_remaining_lambdas(lambda_home_init, lambda_away_init, state, config)
        matrix = _remaining_matrix(adj["lambda_home"], adj["lambda_away"], model, rho, max_goals)
        p_0_0_final = float(matrix[0, 0])  # cero goles restantes de ambos
        curve.append({
            "minute": m,
            "p_home": probs["home"],
            "p_draw": probs["draw"],
            "p_away": probs["away"],
            "p_0_0_final": p_0_0_final,
        })
    return curve
