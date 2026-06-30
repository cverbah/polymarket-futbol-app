"""Lógica pura del dashboard: edge, etiquetas, snapshots y slice de la curva.

Estas funciones NO importan streamlit: son testeables sin una app corriendo.
Toda la matemática vive aquí (o en el motor `src/models/*`), nunca en las
páginas de Streamlit.
"""
from __future__ import annotations

from src.models import analytics, dixon_coles, live_update, poisson


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


def build_live_snapshot(model: dict, match_markets, config: dict) -> dict:
    """Arma el snapshot live desde el modelo guardado y la lectura de mercados.

    Función pura (sin streamlit). Usa los λ guardados como prior de partido
    completo; el motor live los escala al tiempo restante y los condiciona al
    marcador actual. El modelo queda independiente del precio live, así el edge
    (modelo − mercado) es informativo. Devuelve probabilidades 1X2 del resultado
    final, edge por mercado y la mejor oportunidad.
    """
    mm = match_markets
    live = mm.live
    h = live.home_score if live.home_score is not None else 0
    a = live.away_score if live.away_score is not None else 0
    minute = live.minute if live.minute is not None else 0.0

    model_type = model["model_type"]
    rho = model["rho"]
    max_goals = config["max_goals"]

    state = live_update.MatchState(minute=minute, home_score=h, away_score=a)
    adj = live_update.adjusted_remaining_lambdas(
        model["lambda_home"], model["lambda_away"], state, config
    )
    lh_rem, la_rem = adj["lambda_home"], adj["lambda_away"]

    if model_type == "dixon_coles":
        remaining_matrix = dixon_coles.score_matrix(lh_rem, la_rem, rho, max_goals)
    else:
        remaining_matrix = poisson.score_matrix(lh_rem, la_rem, max_goals)
    final_matrix = analytics.final_score_matrix(remaining_matrix, h, a, max_goals)
    probs = analytics.one_x_two(final_matrix)

    market_quotes = [
        {"market": "home", "market_price": mm.one_x_two["home"].price},
        {"market": "draw", "market_price": mm.one_x_two["draw"].price},
        {"market": "away", "market_price": mm.one_x_two["away"].price},
    ]
    for line in analytics.SUPPORTED_OU_LINES:
        if line in mm.over_under:
            market_quotes.append(
                {"market": f"over_{line}", "market_price": mm.over_under[line].price}
            )
    if mm.btts is not None:
        market_quotes.append({"market": "btts", "market_price": mm.btts.price})
    draw_price = mm.one_x_two["draw"].price

    edges = analytics.model_vs_market(final_matrix, lh_rem, la_rem, market_quotes)
    best = next((e for e in edges if e["edge"] is not None), None)

    return {
        "minute": minute,
        "home_score": h,
        "away_score": a,
        "status": live.status,
        "model_home_prob": probs["home"],
        "model_draw_prob": probs["draw"],
        "model_away_prob": probs["away"],
        "market_draw_price": draw_price,
        "edge": compute_edge(probs["draw"], draw_price),
        "edges": edges,
        "best_opportunity": best,
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
