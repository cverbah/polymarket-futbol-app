"""Modelo Poisson independiente para marcadores de futbol.

Goles del local ~ Poisson(lambda_home), goles del visitante ~ Poisson(lambda_away),
independientes. Produce la matriz de marcadores y las probabilidades 1X2.

Ver spec maestro, secciones 6 y 7.
"""
from __future__ import annotations

import numpy as np
from scipy.stats import poisson as _poisson


def score_matrix(lambda_home: float, lambda_away: float, max_goals: int = 12) -> np.ndarray:
    """Matriz (max_goals+1) x (max_goals+1) con P(home=i, away=j).

    P(i, j) = pmf(i; lambda_home) * pmf(j; lambda_away).
    Filas = goles del local, columnas = goles del visitante.
    """
    goals = np.arange(max_goals + 1)
    pmf_home = _poisson.pmf(goals, lambda_home)
    pmf_away = _poisson.pmf(goals, lambda_away)
    # Producto externo: matriz[i, j] = pmf_home[i] * pmf_away[j].
    return np.outer(pmf_home, pmf_away)


def outcome_probs(matrix: np.ndarray) -> dict:
    """Probabilidades 1X2 a partir de la matriz de marcadores.

    home = triangulo inferior (i > j), draw = diagonal (i == j),
    away = triangulo superior (i < j).
    """
    home = float(np.tril(matrix, k=-1).sum())
    draw = float(np.trace(matrix))
    away = float(np.triu(matrix, k=1).sum())
    return {"home": home, "draw": draw, "away": away}


def top_scores(matrix: np.ndarray, n: int = 10) -> list:
    """Devuelve los n marcadores mas probables como (home, away, prob)."""
    flat = matrix.flatten()
    idx = np.argsort(flat)[::-1][:n]
    ncols = matrix.shape[1]
    result = []
    for k in idx:
        i, j = divmod(int(k), ncols)
        result.append((i, j, float(matrix[i, j])))
    return result


def prob_total_goals_at_least(matrix: np.ndarray, k: int) -> float:
    """P(goles totales >= k). Util para Over/Under (k=3 -> Over 2.5)."""
    n = matrix.shape[0]
    total = 0.0
    for i in range(n):
        for j in range(matrix.shape[1]):
            if i + j >= k:
                total += matrix[i, j]
    return float(total)
