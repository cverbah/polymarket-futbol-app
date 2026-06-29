"""Lógica pura del dashboard: edge, etiquetas, snapshots y slice de la curva.

Estas funciones NO importan streamlit: son testeables sin una app corriendo.
Toda la matemática vive aquí (o en el motor `src/models/*`), nunca en las
páginas de Streamlit.
"""
from __future__ import annotations

from src.models import live_update


def compute_edge(model_draw_prob: float, market_draw_price: float) -> float:
    """Edge del empate: probabilidad del modelo menos precio del mercado."""
    return model_draw_prob - market_draw_price


def describe_edge(edge: float, tol: float = 0.005) -> str:
    """Etiqueta descriptiva factual (no es una señal de trade).

    El signo va incluido en el número mostrado (p. ej. "+4.2" / "-1.5").
    Dentro de la tolerancia se considera que modelo y mercado coinciden.
    """
    if edge > tol:
        return f"El modelo ve el empate +{edge * 100:.1f} pts vs el mercado"
    if edge < -tol:
        return f"El modelo ve el empate {edge * 100:.1f} pts vs el mercado"
    return "Modelo y mercado coinciden en el empate"


def build_snapshot(model: dict, match_state, market_draw_price: float, config: dict) -> dict:
    """Corre el motor live y arma el dict del snapshot.

    Función pura: deriva modelo/rho del dict `model`, calcula probabilidades
    live, lambdas restantes y edge. No toca Streamlit.
    """
    model_type = model["model_type"]
    rho = model["rho"]
    lambda_home = model["lambda_home"]
    lambda_away = model["lambda_away"]

    probs = live_update.live_outcome_probs(
        lambda_home, lambda_away, match_state, config, model=model_type, rho=rho
    )
    remaining = live_update.adjusted_remaining_lambdas(
        lambda_home, lambda_away, match_state, config
    )

    edge = compute_edge(probs["draw"], market_draw_price)

    return {
        "minute": match_state.minute,
        "home_score": match_state.home_score,
        "away_score": match_state.away_score,
        "home_xg": match_state.home_xg,
        "away_xg": match_state.away_xg,
        "model_home_prob": probs["home"],
        "model_draw_prob": probs["draw"],
        "model_away_prob": probs["away"],
        "market_draw_price": market_draw_price,
        "edge": edge,
        "lambda_home_remaining": remaining["lambda_home"],
        "lambda_away_remaining": remaining["lambda_away"],
    }


def forward_draw_curve(model: dict, config: dict, current_minute: float) -> list:
    """Curva del empate forward: solo puntos desde el minuto actual hasta 90.

    Envuelve `live_update.fair_draw_curve` y filtra los puntos con
    `minute >= current_minute`, asegurando que el minuto 90 esté incluido.
    """
    curve = live_update.fair_draw_curve(
        model["lambda_home"],
        model["lambda_away"],
        config,
        model=model["model_type"],
        rho=model["rho"],
    )
    return [point for point in curve if point["minute"] >= current_minute]
