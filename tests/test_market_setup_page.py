"""AppTest de la pagina Market Setup time-aware (spec D, seccion 5 y 6).

Sin red: se parsea la lista de partidos y los mercados del partido desde los
fixtures JSON reales usando las funciones de parsing puras del connector, y se
mockean las funciones de alto nivel `pm.list_world_cup_matches` /
`pm.get_match_markets` con esos objetos. Se limpia el cache de Streamlit antes de
correr para que los wrappers cacheados no opaquen el patch.

Regla de scope del mock: el `with patch(...)` debe seguir activo durante TODO el
test, incluido cualquier segundo `.run()`. Por eso `_patched`/`_patched_with`
son context managers que hacen `yield` DENTRO del `with patch(...)`; nunca se
retorna `at` fuera del scope del patch (de lo contrario el segundo `.run()`
pegaria a la red real).
"""
import json
import os
from contextlib import contextmanager
from unittest.mock import patch

import streamlit as st
from streamlit.testing.v1 import AppTest

from src.connectors import polymarket as pm
from src.dashboard import state

SETUP = "app/pages/01_market_setup.py"
_FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
_PM_CONFIG = {"max_spread": 0.06, "min_liquidity": 500}


def _load(name: str):
    with open(os.path.join(_FIXTURES, name), "r") as f:
        return json.load(f)


def _match_list():
    return pm.parse_match_list(_load("wc_events_list.json"), "fifwc-")


def _germany_paraguay_markets():
    """Germany vs Paraguay: el fixture principal es LIVE 0-0 (1H, min 13)."""
    main = _load("wc_match_main.json")[0]
    more = _load("wc_match_more_markets.json")[0]
    return pm.parse_match_markets(main, more, _PM_CONFIG)


def _live_scored_markets():
    """Germany vs Paraguay LIVE 1-1 (2H, min 70). Sin more-markets."""
    main = _load("wc_match_live_scored.json")[0]
    return pm.parse_match_markets(main, None, _PM_CONFIG)


def _pre_markets():
    """Netherlands vs Morocco PRE-partido (no empezado). Sin more-markets."""
    main = _load("wc_match_pre.json")[0]
    return pm.parse_match_markets(main, None, _PM_CONFIG)


def _post_markets():
    """Brazil vs Japan TERMINADO (VFT 2-1). Sin more-markets."""
    main = _load("wc_match_post.json")[0]
    return pm.parse_match_markets(main, None, _PM_CONFIG)


@contextmanager
def _patched_with(markets):
    """Corre la pagina con la lista y unos mercados dados, sin red.

    El patch sigue activo durante el `yield` (y cualquier `.run()` posterior).
    """
    st.cache_data.clear()  # evita que los wrappers cacheados opaquen el patch
    matches = _match_list()
    with patch.object(pm, "list_world_cup_matches", return_value=matches), \
            patch.object(pm, "get_match_markets", return_value=markets):
        at = AppTest.from_file(SETUP)
        at.default_timeout = 30
        at.run()
        yield at, matches, markets


@contextmanager
def _patched():
    """Atajo: corre la pagina con los mercados live 0-0 (Germany vs Paraguay)."""
    with _patched_with(_germany_paraguay_markets()) as ctx:
        yield ctx


def _all_text(at) -> str:
    """Concatena el texto visible de los elementos comunes para asserts laxos."""
    chunks = []
    for coll in (
        at.markdown, at.caption, at.success, at.info, at.warning, at.error, at.subheader
    ):
        for el in coll:
            chunks.append(str(getattr(el, "value", "")))
    return "\n".join(chunks)


# --------------------------------------------------------------------------- #
# LIVE 0-0 (fixture principal): banner + modelo guardado
# --------------------------------------------------------------------------- #
def test_page_runs_without_exception():
    with _patched() as (at, _, _):
        assert not at.exception


def test_live_banner_and_model_saved():
    with _patched() as (at, matches, markets):
        assert not at.exception

        text = _all_text(at)
        assert "EN VIVO" in text
        # min 13 del fixture aparece en el banner.
        assert "13" in text

        model = at.session_state[state.MODEL_KEY]
        assert model is not None
        assert model["lambda_home"] > 0
        assert model["lambda_away"] > 0
        assert "rho" in model
        assert model["model_type"] in ("dixon_coles", "poisson")
        assert model["metadata"]["home_team"] == "Germany"
        assert model["metadata"]["away_team"] == "Paraguay"
        # Bloque live presente en metadata (compatibilidad Live Match).
        live = model["metadata"]["live"]
        assert live["status"] == "in"
        assert live["home_score"] == 0
        assert live["away_score"] == 0
        # Favorito fuerte: Germany => lambda restante local > visita.
        assert model["lambda_home"] > model["lambda_away"]

        # La proyeccion final renderiza la tabla Modelo vs Mercado.
        assert len(at.dataframe) >= 1
        assert "Proyección final" in text


def test_default_model_is_dixon_coles():
    with _patched() as (at, _, _):
        assert not at.exception
        model = at.session_state[state.MODEL_KEY]
        assert model["model_type"] == "dixon_coles"


# --------------------------------------------------------------------------- #
# LIVE 1-1: banner con marcador y proyeccion sin error
# --------------------------------------------------------------------------- #
def test_live_scored_renders_projection():
    with _patched_with(_live_scored_markets()) as (at, _, _):
        assert not at.exception

        text = _all_text(at)
        assert "EN VIVO" in text
        # Marcador 1-1 en el banner.
        assert "1-1" in text

        model = at.session_state[state.MODEL_KEY]
        assert model["metadata"]["live"]["home_score"] == 1
        assert model["metadata"]["live"]["away_score"] == 1
        assert model["lambda_home"] > 0
        assert model["lambda_away"] > 0

        # BTTS Si ~ 1: ambos ya anotaron, en cualquier marcador final ambos >=1.
        btts_metric = next(
            (m for m in at.metric if "BTTS Si" in str(getattr(m, "label", ""))),
            None,
        )
        assert btts_metric is not None
        assert float(btts_metric.value) > 0.99


# --------------------------------------------------------------------------- #
# Bug de seleccion: al refrescar la lista NO debe resetear al primer partido
# --------------------------------------------------------------------------- #
def test_selection_persists_after_list_refresh():
    st.cache_data.clear()
    matches = _match_list()
    assert len(matches) >= 2
    target = matches[1]  # un partido que NO es el primero de la lista
    markets = _germany_paraguay_markets()

    with patch.object(pm, "list_world_cup_matches") as mock_list, \
            patch.object(pm, "get_match_markets", return_value=markets):
        mock_list.return_value = matches
        at = AppTest.from_file(SETUP)
        at.default_timeout = 30
        at.run()

        # El usuario elige el segundo partido.
        at.selectbox[0].select(target.slug).run()
        assert at.selectbox[0].value == target.slug

        # Simula un refetch real: mismos partidos, distinta liquidez/volumen
        # (es justo este cambio de valores el que rompia la igualdad por objeto).
        refreshed = _match_list()
        for m in refreshed:
            m.total_liquidity += 50000.0
            m.total_volume += 50000.0
        mock_list.return_value = refreshed

        # Click "Actualizar lista" (primer boton de la pagina) -> limpia cache.
        at.button[0].click().run()

        # La seleccion debe persistir, NO resetear al primer partido.
        assert at.selectbox[0].value == target.slug
        assert at.selectbox[0].value != matches[0].slug


# --------------------------------------------------------------------------- #
# PRE-partido: comportamiento de hoy
# --------------------------------------------------------------------------- #
def test_pre_match_path_saves_model():
    with _patched_with(_pre_markets()) as (at, _, markets):
        assert not at.exception

        text = _all_text(at)
        # Banner de estado destacado: el partido aun no comienza.
        assert "Aún no comienza" in text
        assert "EN VIVO" not in text

        model = at.session_state[state.MODEL_KEY]
        assert model is not None
        assert model["lambda_home"] > 0
        assert model["lambda_away"] > 0
        # En pre-partido NO se agrega el bloque live a metadata.
        assert "live" not in model["metadata"]
        assert model["metadata"]["home_team"] == "Netherlands"
        assert model["metadata"]["away_team"] == "Morocco"


# --------------------------------------------------------------------------- #
# TERMINADO: marcador final + nota, sin proyeccion
# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# Robustez: precios incompletos desde Polymarket (outcomePrices vacio/malformado)
# --------------------------------------------------------------------------- #
def test_missing_required_1x2_price_shows_error_not_crash():
    """Si Gamma devuelve un mercado 1X2 con price=None, la pagina debe avisar
    en vez de crashear formateando None con :.3f (bug encontrado en auditoria)."""
    markets = _germany_paraguay_markets()
    markets.one_x_two["home"].price = None
    with _patched_with(markets) as (at, _, _):
        assert not at.exception
        text = _all_text(at)
        assert "no tiene los 3 mercados 1X2 completos" in text


def test_missing_ou_line_price_does_not_crash_and_is_excluded():
    """Una linea O/U presente pero con price=None no debe crashear la tabla ni
    la comparativa Modelo vs Mercado: se trata igual que linea ausente."""
    markets = _germany_paraguay_markets()
    markets.over_under[2.5].price = None
    with _patched_with(markets) as (at, _, _):
        assert not at.exception
        # No debe aparecer una fila "Over 2.5" rota en Modelo vs Mercado.
        mvm_df = at.dataframe[0].value
        assert "Over 2.5" not in mvm_df["Mercado"].tolist()


def test_missing_btts_price_does_not_crash():
    markets = _germany_paraguay_markets()
    markets.btts.price = None
    with _patched_with(markets) as (at, _, _):
        assert not at.exception


# --------------------------------------------------------------------------- #
# Robustez: calibracion en vivo debe avisar si no reproduce bien el mercado
# (la calibracion pre-partido ya lo hacia; faltaba en calibrate_remaining).
# --------------------------------------------------------------------------- #
def test_live_warns_when_market_contradicts_scoreline():
    markets = _germany_paraguay_markets()
    markets.live.home_score = 5
    markets.live.away_score = 0
    markets.one_x_two["home"].price = 0.05
    markets.one_x_two["draw"].price = 0.05
    markets.one_x_two["away"].price = 0.90
    with _patched_with(markets) as (at, _, _):
        assert not at.exception
        text = _all_text(at)
        assert "El modelo puede no reproducir bien el mercado" in text


def test_post_match_shows_finished_message():
    with _patched_with(_post_markets()) as (at, _, _):
        assert not at.exception

        text = _all_text(at)
        # Banner de estado destacado: partido finalizado.
        assert "Finalizado" in text
        assert "Partido terminado" in text
        # Marcador final 2-1 mostrado.
        assert "2 - 1" in text
        # No se calibro ni guardo nada (no llego a la fase de modelo).
        # (st.stop tras el mensaje => no hay tabla Modelo vs Mercado).
        assert "Modelo vs Mercado" not in text
