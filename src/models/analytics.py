"""Derivaciones analiticas puras desde la matriz de marcadores y los lambdas.

Modulo SIN estado, SIN red, SIN dependencia de Streamlit ni del connector. Todo
se calcula de forma exacta (no Monte Carlo) a partir de la matriz de marcadores
producida por `poisson.score_matrix` / `dixon_coles.score_matrix` y/o de los
lambdas. Ver spec de diseno, seccion 4.2.

`model_vs_market` acepta `market_quotes` como `list[dict]` plano para mantener el
modulo desacoplado del connector: no importa ningun tipo de Polymarket.
"""
from __future__ import annotations

import math

import numpy as np

from src.models import poisson

# Lineas Over/Under soportadas como nombres canonicos "over_{L}".
SUPPORTED_OU_LINES = (0.5, 1.5, 2.5, 3.5, 4.5)


def expected_goals(lambda_home: float, lambda_away: float) -> dict:
    """Goles esperados de local, visita y total (= los propios lambdas)."""
    return {
        "home": float(lambda_home),
        "away": float(lambda_away),
        "total": float(lambda_home + lambda_away),
    }


def one_x_two(matrix: np.ndarray) -> dict:
    """Probabilidades 1X2 (reusa poisson.outcome_probs)."""
    return poisson.outcome_probs(matrix)


def double_chance(one_x_two_probs: dict) -> dict:
    """Doble oportunidad: 1X (home_or_draw), 12 (home_or_away), X2 (draw_or_away)."""
    home = one_x_two_probs["home"]
    draw = one_x_two_probs["draw"]
    away = one_x_two_probs["away"]
    return {
        "home_or_draw": home + draw,
        "home_or_away": home + away,
        "draw_or_away": draw + away,
    }


def total_goals_distribution(matrix: np.ndarray, up_to: int = 5) -> dict:
    """Distribucion de goles totales: P(0), P(1), ..., y un bucket final ">={up_to}".

    Suma sobre las anti-diagonales i + j = k para k en [0, up_to). El ultimo
    bucket "{up_to}+" agrupa P(total >= up_to).
    """
    n_rows, n_cols = matrix.shape
    dist: dict = {}
    for k in range(up_to):
        total = 0.0
        for i in range(min(k, n_rows - 1) + 1):
            j = k - i
            if 0 <= j < n_cols:
                total += matrix[i, j]
        dist[k] = float(total)
    dist[f"{up_to}+"] = poisson.prob_total_goals_at_least(matrix, up_to)
    return dist


def over_under(matrix: np.ndarray, line: float) -> dict:
    """Over/Under para una linea (ej. 2.5). Over = P(goles totales > line)."""
    # Como las lineas son semienteras, P(total > line) = P(total >= ceil(line)).
    threshold = math.ceil(line)
    over = poisson.prob_total_goals_at_least(matrix, threshold)
    return {"over": over, "under": 1.0 - over}


def btts(matrix: np.ndarray) -> dict:
    """Both Teams To Score: yes = P(local>=1 y visita>=1) = suma matrix[1:, 1:]."""
    yes = float(matrix[1:, 1:].sum())
    return {"yes": yes, "no": 1.0 - yes}


def clean_sheets(matrix: np.ndarray) -> dict:
    """Valla invicta: home = visita no anota (suma col 0); away = local no anota (fila 0)."""
    home = float(matrix[:, 0].sum())
    away = float(matrix[0, :].sum())
    return {"home": home, "away": away}


def first_to_score(lambda_home: float, lambda_away: float) -> dict:
    """Primer equipo en anotar (los tres suman 1).

    none = exp(-(lh+la)); home = (1-none)*lh/(lh+la); away = (1-none)*la/(lh+la).
    """
    total_lambda = lambda_home + lambda_away
    none = math.exp(-total_lambda)
    if total_lambda == 0:
        return {"home": 0.0, "away": 0.0, "none": 1.0}
    scored = 1.0 - none
    return {
        "home": scored * lambda_home / total_lambda,
        "away": scored * lambda_away / total_lambda,
        "none": none,
    }


def winning_margin(matrix: np.ndarray) -> dict:
    """Margen de victoria desde las diagonales de la matriz.

    Buckets: home_by_1/2/3+, draw, away_by_1/2/3+. Suman 1.
    """
    n_rows, n_cols = matrix.shape
    margin = {
        "home_by_1": 0.0,
        "home_by_2": 0.0,
        "home_by_3+": 0.0,
        "draw": 0.0,
        "away_by_1": 0.0,
        "away_by_2": 0.0,
        "away_by_3+": 0.0,
    }
    for i in range(n_rows):
        for j in range(n_cols):
            p = float(matrix[i, j])
            diff = i - j
            if diff == 0:
                margin["draw"] += p
            elif diff > 0:
                if diff == 1:
                    margin["home_by_1"] += p
                elif diff == 2:
                    margin["home_by_2"] += p
                else:
                    margin["home_by_3+"] += p
            else:
                d = -diff
                if d == 1:
                    margin["away_by_1"] += p
                elif d == 2:
                    margin["away_by_2"] += p
                else:
                    margin["away_by_3+"] += p
    return margin


def top_scores(matrix: np.ndarray, n: int = 10) -> list:
    """Los n marcadores mas probables (reusa poisson.top_scores)."""
    return poisson.top_scores(matrix, n)


def _model_prob_for_market(matrix: np.ndarray, name: str):
    """Probabilidad del modelo para un nombre canonico de mercado, o None si no se reconoce."""
    probs = one_x_two(matrix)
    if name in ("home", "draw", "away"):
        return probs[name]
    if name == "btts":
        return btts(matrix)["yes"]
    if name.startswith("over_"):
        try:
            line = float(name[len("over_"):])
        except ValueError:
            return None
        if line in SUPPORTED_OU_LINES:
            return over_under(matrix, line)["over"]
        return None
    return None


def model_vs_market(
    matrix: np.ndarray,
    lambda_home: float,
    lambda_away: float,
    market_quotes: list,
) -> list:
    """Compara la probabilidad del modelo contra el precio de mercado por mercado.

    `market_quotes` es una lista de dicts planos, cada uno con las claves
    "market" (nombre canonico) y "market_price" (float). Nombres canonicos
    reconocidos: "home"/"draw"/"away", "over_{L}" con L en 0.5/1.5/2.5/3.5/4.5,
    y "btts".

    Devuelve una lista de dicts
    {"market", "model_prob", "market_price", "edge"} con edge = model_prob -
    market_price, ordenada por |edge| descendente. Mercados no reconocidos se
    incluyen con model_prob=None y edge=None (no participan del orden).
    """
    rows = []
    for quote in market_quotes:
        name = quote["market"]
        price = quote["market_price"]
        model_prob = _model_prob_for_market(matrix, name)
        edge = None if model_prob is None else model_prob - price
        rows.append(
            {
                "market": name,
                "model_prob": model_prob,
                "market_price": price,
                "edge": edge,
            }
        )
    rows.sort(key=lambda r: abs(r["edge"]) if r["edge"] is not None else -1.0, reverse=True)
    return rows
