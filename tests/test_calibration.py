"""Tests de calibracion (spec maestro seccion 7, 20.1)."""
import pytest

from src.models import calibration, live_update, poisson
from src.utils.config import load_config


def test_normalize_prices():
    norm = calibration.normalize_prices(0.86, 0.11, 0.04)
    assert abs(sum(norm.values()) - 1.0) < 1e-9
    assert abs(norm["home"] - 0.8515) < 1e-3
    assert abs(norm["draw"] - 0.1089) < 1e-3
    assert abs(norm["away"] - 0.0396) < 1e-3


def test_calibrate_argentina_cabo_verde():
    """Reproduce el ejemplo: lambdas ~ (2.76, 0.46) en Poisson."""
    target = calibration.normalize_prices(0.86, 0.11, 0.04)
    result = calibration.calibrate(target, model="poisson")
    assert result["success"]
    assert 2.3 < result["lambda_home"] < 3.2
    assert 0.3 < result["lambda_away"] < 0.7
    # El modelo calibrado debe reproducir el mercado razonablemente.
    m = poisson.score_matrix(result["lambda_home"], result["lambda_away"])
    probs = poisson.outcome_probs(m)
    assert abs(probs["home"] - target["home"]) < 0.05


def test_calibrate_returns_expected_keys():
    target = calibration.normalize_prices(0.50, 0.27, 0.23)
    result = calibration.calibrate(target, model="poisson")
    for key in ("lambda_home", "lambda_away", "rho", "loss", "success", "warnings"):
        assert key in result


def test_calibrate_balanced_match_is_low_loss():
    """Un partido parejo deberia calibrarse con perdida pequena."""
    target = calibration.normalize_prices(0.40, 0.30, 0.30)
    result = calibration.calibrate(target, model="poisson")
    assert result["loss"] < 1e-3


def test_warning_fires_when_model_misses_market():
    """Poisson simple no puede dar a la vez favorito claro y empate muy alto:
    la advertencia debe dispararse cuando el modelo se aleja > 0.03."""
    # Favorito claro con away minusculo y empate alto: estructuralmente
    # inalcanzable para Poisson (el away se ve forzado hacia arriba).
    target = calibration.normalize_prices(0.60, 0.35, 0.05)
    result = calibration.calibrate(target, model="poisson")
    assert result["warnings"]


def test_calibrate_dixon_coles_default_rho():
    """Sin Over/Under, Dixon-Coles usa rho fijo del config (no lo libera)."""
    target = calibration.normalize_prices(0.50, 0.27, 0.23)
    result = calibration.calibrate(target, model="dixon_coles")
    from src.utils.config import load_config
    cfg = load_config()
    assert abs(result["rho"] - cfg["default_rho"]) < 1e-9


def test_calibrate_dixon_coles_with_over_frees_rho():
    """Con Over/Under, rho se libera como tercer parametro."""
    target = calibration.normalize_prices(0.50, 0.27, 0.23)
    result = calibration.calibrate(
        target, model="dixon_coles", over_2_5_price=0.45
    )
    assert result["success"]
    # rho calibrado puede diferir del default.
    assert -1.0 <= result["rho"] <= 1.0


# --- Calibracion live: lambdas restantes condicionados al marcador ---------


def test_calibrate_remaining_round_trip():
    """Round-trip: dados lambdas restantes y un marcador, calcular el 1X2
    condicionado, realimentarlo y recuperar los lambdas dentro de tolerancia."""
    cfg = load_config()
    model = "dixon_coles"
    rho = cfg["default_rho"]
    H, A = 1, 1
    true_lh_rem, true_la_rem = 1.4, 0.9

    target = live_update.remaining_outcome_probs(
        true_lh_rem, true_la_rem, H, A, model=model, rho=rho,
        max_goals=cfg["max_goals"],
    )

    result = calibration.calibrate_remaining(
        target, home_score=H, away_score=A, model=model, rho=rho, config=cfg
    )
    assert result["success"]
    for key in ("lambda_home_remaining", "lambda_away_remaining", "rho", "loss", "success"):
        assert key in result

    # Recupera los lambdas verdaderos.
    assert abs(result["lambda_home_remaining"] - true_lh_rem) < 0.05
    assert abs(result["lambda_away_remaining"] - true_la_rem) < 0.05

    # Reproduce las probabilidades objetivo.
    recovered = live_update.remaining_outcome_probs(
        result["lambda_home_remaining"], result["lambda_away_remaining"],
        H, A, model=model, rho=rho, max_goals=cfg["max_goals"],
    )
    for k in ("home", "draw", "away"):
        assert abs(recovered[k] - target[k]) < 1e-3


def test_calibrate_remaining_at_0_0_matches_prematch():
    """Con (H, A) = (0, 0), los lambdas restantes ~ los lambdas full que
    encuentra la calibracion pre-partido para el mismo target (direccional)."""
    cfg = load_config()
    target = calibration.normalize_prices(0.55, 0.27, 0.18)

    pre = calibration.calibrate(target, model="dixon_coles", config=cfg)
    live = calibration.calibrate_remaining(
        target, home_score=0, away_score=0, model="dixon_coles", config=cfg
    )

    assert live["success"]
    # Tolerancia laxa: misma estructura, debe quedar cerca del full-match lambda.
    assert abs(live["lambda_home_remaining"] - pre["lambda_home"]) < 0.15
    assert abs(live["lambda_away_remaining"] - pre["lambda_away"]) < 0.15
