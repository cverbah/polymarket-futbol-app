"""Validaciones y advertencias del motor de probabilidades.

Checks simples: las probabilidades suman ~1, las lambdas son positivas, y la
advertencia de calibracion cuando el modelo se aleja del mercado > 0.03.

Ver spec maestro seccion 7.4.
"""
from __future__ import annotations

# Tolerancia para la diferencia modelo vs mercado en cada outcome 1X2.
MARKET_TOLERANCE = 0.03


def probs_sum_to_one(probs: dict, tol: float = 0.01) -> bool:
    """True si la suma de las probabilidades esta en [1 - tol, 1 + tol]."""
    total = sum(probs.values())
    return (1.0 - tol) <= total <= (1.0 + tol)


def lambdas_positive(*lambdas: float) -> bool:
    """True si todas las lambdas son estrictamente positivas."""
    return all(lam > 0 for lam in lambdas)


def calibration_warnings(model_probs: dict, market_probs: dict,
                         tol: float = MARKET_TOLERANCE) -> list:
    """Lista de advertencias si |modelo - mercado| > tol en algun outcome.

    Devuelve una lista de strings (vacia si todo esta dentro de tolerancia).
    """
    warnings = []
    for key in ("home", "draw", "away"):
        diff = abs(model_probs.get(key, 0.0) - market_probs.get(key, 0.0))
        if diff > tol:
            warnings.append(
                f"Outcome '{key}': el modelo difiere del mercado en {diff:.3f} "
                f"(> {tol}). El modelo puede no reproducir bien el mercado."
            )
    return warnings
