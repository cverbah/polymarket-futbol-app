"""Calibracion de lambdas (y rho) desde precios de mercado 1X2.

Encuentra los parametros que mejor reproducen las probabilidades implicitas del
mercado, minimizando una perdida ponderada (scipy L-BFGS-B).

- Poisson: calibra (lambda_home, lambda_away).
- Dixon-Coles sin Over/Under: rho fijo en config `default_rho`, calibra 2 lambdas.
- Dixon-Coles con Over/Under: agrega termino Over 2.5 y libera rho (3 params).

Ver spec maestro secciones 7 y 8.1.
"""
from __future__ import annotations

from scipy.optimize import minimize

from src.models import poisson, dixon_coles, live_update
from src.utils.config import load_config
from src.utils.validation import calibration_warnings


def normalize_prices(p_home: float, p_draw: float, p_away: float) -> dict:
    """Normaliza precios crudos 1X2 a probabilidades que suman 1."""
    total = p_home + p_draw + p_away
    return {
        "home": p_home / total,
        "draw": p_draw / total,
        "away": p_away / total,
    }


def _model_probs(lambda_home, lambda_away, rho, model, max_goals):
    """Probabilidades 1X2 segun el modelo elegido."""
    if model == "dixon_coles":
        matrix = dixon_coles.score_matrix(lambda_home, lambda_away, rho, max_goals)
    else:
        matrix = poisson.score_matrix(lambda_home, lambda_away, max_goals)
    return poisson.outcome_probs(matrix), matrix


def calibrate(
    target_probs: dict,
    model: str = "poisson",
    over_2_5_price: float | None = None,
    config: dict | None = None,
) -> dict:
    """Calibra los parametros del modelo a las probabilidades objetivo.

    Devuelve {lambda_home, lambda_away, rho, loss, success, warnings}.
    """
    cfg = config if config is not None else load_config()
    max_goals = cfg["max_goals"]
    w_home = 1.0
    w_draw = cfg["draw_weight"]
    w_away = 1.0
    w_over = cfg["over_weight"]
    default_rho = cfg["default_rho"]

    # Decidir si rho es libre: solo Dixon-Coles + Over/Under.
    free_rho = model == "dixon_coles" and over_2_5_price is not None

    def objective(x):
        lambda_home, lambda_away = x[0], x[1]
        rho = x[2] if free_rho else default_rho
        model_probs, matrix = _model_probs(
            lambda_home, lambda_away, rho, model, max_goals
        )
        loss = (
            w_home * (model_probs["home"] - target_probs["home"]) ** 2
            + w_draw * (model_probs["draw"] - target_probs["draw"]) ** 2
            + w_away * (model_probs["away"] - target_probs["away"]) ** 2
        )
        if over_2_5_price is not None:
            model_over = poisson.prob_total_goals_at_least(matrix, 3)
            loss += w_over * (model_over - over_2_5_price) ** 2
        return loss

    bounds = [tuple(cfg["lambda_home_bounds"]), tuple(cfg["lambda_away_bounds"])]
    x0 = [1.7, 1.0]
    if free_rho:
        bounds.append((-1.0, 1.0))
        x0.append(default_rho)

    result = minimize(objective, x0=x0, bounds=bounds, method="L-BFGS-B")

    lambda_home, lambda_away = float(result.x[0]), float(result.x[1])
    rho = float(result.x[2]) if free_rho else default_rho

    final_probs, _ = _model_probs(
        lambda_home, lambda_away, rho, model, max_goals
    )
    warnings = calibration_warnings(final_probs, target_probs)

    return {
        "lambda_home": lambda_home,
        "lambda_away": lambda_away,
        "rho": rho,
        "loss": float(result.fun),
        "success": bool(result.success),
        "warnings": warnings,
    }


def calibrate_remaining(
    target_probs: dict,
    home_score: int,
    away_score: int,
    model: str = "dixon_coles",
    rho: float | None = None,
    config: dict | None = None,
) -> dict:
    """Calibra los lambdas RESTANTES al precio live 1X2 condicionado al marcador.

    Dado el 1X2 live normalizado + el marcador actual (home_score, away_score),
    optimiza (lambda_home_remaining, lambda_away_remaining) tal que el modelo
    condicionado al marcador (goles restantes Poisson/Dixon-Coles, resultado
    final = (H+i, A+j)) reproduzca `target_probs`.

    `rho` queda fijo (default del config si es None): con solo 1X2 no se
    identifica un tercer parametro. Caso (0, 0) ~ calibracion pre-partido.

    Devuelve {lambda_home_remaining, lambda_away_remaining, rho, loss, success}.
    """
    cfg = config if config is not None else load_config()
    max_goals = cfg["max_goals"]
    w_home = 1.0
    w_draw = cfg["draw_weight"]
    w_away = 1.0
    fixed_rho = cfg["default_rho"] if rho is None else rho

    def objective(x):
        lambda_home_rem, lambda_away_rem = x[0], x[1]
        probs = live_update.remaining_outcome_probs(
            lambda_home_rem,
            lambda_away_rem,
            home_score,
            away_score,
            model=model,
            rho=fixed_rho,
            max_goals=max_goals,
        )
        return (
            w_home * (probs["home"] - target_probs["home"]) ** 2
            + w_draw * (probs["draw"] - target_probs["draw"]) ** 2
            + w_away * (probs["away"] - target_probs["away"]) ** 2
        )

    bounds = [(1e-3, 8.0), (1e-3, 8.0)]
    x0 = [1.0, 1.0]
    result = minimize(objective, x0=x0, bounds=bounds, method="L-BFGS-B")

    return {
        "lambda_home_remaining": float(result.x[0]),
        "lambda_away_remaining": float(result.x[1]),
        "rho": float(fixed_rho),
        "loss": float(result.fun),
        "success": bool(result.success),
    }
