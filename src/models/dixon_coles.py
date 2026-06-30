"""Modelo Dixon-Coles: correccion de marcadores bajos sobre Poisson.

El Poisson independiente subestima 0-0, 1-0, 0-1 y 1-1. Dixon-Coles aplica un
factor tau(i, j; rho) a esos cuatro marcadores y re-normaliza la matriz.

Misma interfaz que poisson.py (intercambiable). Reusa outcome_probs / top_scores /
prob_total_goals_at_least desde poisson.py.

Ver spec maestro, nota de modelado en CLAUDE.md.
"""
from __future__ import annotations

import numpy as np

from src.models.poisson import (
    score_matrix as _poisson_score_matrix,
    outcome_probs,  # re-exportadas para interfaz comun
    top_scores,
    prob_total_goals_at_least,
)

__all__ = [
    "score_matrix",
    "outcome_probs",
    "top_scores",
    "prob_total_goals_at_least",
    "tau",
]


def tau(i: int, j: int, lambda_home: float, lambda_away: float, rho: float) -> float:
    """Factor de correccion Dixon-Coles para los cuatro marcadores bajos.

    Formulacion estandar (Dixon & Coles, 1997):
        0-0: 1 - lambda_home * lambda_away * rho
        0-1: 1 + lambda_home * rho
        1-0: 1 + lambda_away * rho
        1-1: 1 - rho
    Cualquier otro marcador: 1 (sin correccion).
    """
    if i == 0 and j == 0:
        return 1.0 - lambda_home * lambda_away * rho
    if i == 0 and j == 1:
        return 1.0 + lambda_home * rho
    if i == 1 and j == 0:
        return 1.0 + lambda_away * rho
    if i == 1 and j == 1:
        return 1.0 - rho
    return 1.0


def score_matrix(
    lambda_home: float,
    lambda_away: float,
    rho: float,
    max_goals: int = 12,
) -> np.ndarray:
    """Matriz de marcadores Poisson con correccion Dixon-Coles re-normalizada."""
    matrix = _poisson_score_matrix(lambda_home, lambda_away, max_goals).copy()
    # Aplicar tau solo a los cuatro marcadores bajos.
    for i in (0, 1):
        for j in (0, 1):
            matrix[i, j] *= tau(i, j, lambda_home, lambda_away, rho)
    # Con rho/lambdas extremos tau puede volverse negativo: recortar a 0 para
    # mantener una distribucion de probabilidad valida antes de re-normalizar.
    np.clip(matrix, 0.0, None, out=matrix)
    # Re-normalizar para que sume 1 (tau puede romper la suma).
    matrix /= matrix.sum()
    return matrix
