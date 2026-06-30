"""Tests del conector Polymarket. Sin red: usan fixtures JSON reales."""
import json
import os

import pytest

from src.connectors.polymarket import (
    GammaClient,
    LiveState,
    MarketQuote,
    MatchMarkets,
    MatchSummary,
    PolymarketError,
    get_match_markets,
    list_world_cup_matches,
    parse_espn_scoreboard,
    parse_live_state,
    parse_match_list,
    parse_match_markets,
    parse_more_markets,
)

_FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def _load(name: str):
    with open(os.path.join(_FIXTURES, name), "r") as f:
        return json.load(f)


@pytest.fixture
def main_event():
    return _load("wc_match_main.json")[0]


@pytest.fixture
def more_event():
    return _load("wc_match_more_markets.json")[0]


@pytest.fixture
def events_list():
    return _load("wc_events_list.json")


@pytest.fixture
def config():
    return {"max_spread": 0.06, "min_liquidity": 500}


# --------------------------------------------------------------------------- #
# parse_match_markets sobre los dos fixtures del partido
# --------------------------------------------------------------------------- #
def test_parse_match_markets_germany_paraguay(main_event, more_event, config):
    mm = parse_match_markets(main_event, more_event, config)

    assert isinstance(mm, MatchMarkets)
    # Equipos
    assert mm.summary.home_team == "Germany"
    assert mm.summary.away_team == "Paraguay"
    assert mm.summary.slug == "fifwc-ger-par-2026-06-29"
    assert mm.summary.total_liquidity > 0
    assert mm.summary.total_volume > 0

    # 1X2
    assert mm.one_x_two["home"].price == pytest.approx(0.715, abs=0.01)
    assert mm.one_x_two["draw"].price == pytest.approx(0.195, abs=0.01)
    assert mm.one_x_two["away"].price == pytest.approx(0.085, abs=0.01)

    # O/U total: la linea 2.5 existe y el precio es el OVER
    assert 2.5 in mm.over_under
    assert mm.over_under[2.5].name == "over_2.5"
    assert mm.over_under[2.5].price == pytest.approx(0.495, abs=0.01)

    # BTTS = precio Yes
    assert mm.btts is not None
    assert mm.btts.name == "btts"
    assert mm.btts.price == pytest.approx(0.415, abs=0.01)

    # Calidad OK (spreads ~0.01)
    assert mm.quality_flags == ["OK"]


def test_over_under_excludes_per_team_and_halftime(main_event, more_event, config):
    over_under, btts = parse_more_markets(more_event)
    # Solo lineas totales del partido (0.5..8.5), sin O/U por equipo ni por tiempo.
    lines = sorted(over_under.keys())
    assert lines == [0.5, 1.5, 2.5, 3.5, 4.5, 5.5, 6.5, 7.5, 8.5]
    # BTTS total (no de primer/segundo tiempo): Yes ~0.415
    assert btts.price == pytest.approx(0.415, abs=0.01)


# --------------------------------------------------------------------------- #
# parse_match_list sobre la lista de eventos
# --------------------------------------------------------------------------- #
def test_parse_match_list(events_list):
    summaries = parse_match_list(events_list, "fifwc-")
    assert len(summaries) == 14
    assert all(isinstance(s, MatchSummary) for s in summaries)
    # Equipos parseados con " vs. "
    by_slug = {s.slug: s for s in summaries}
    ger = by_slug["fifwc-ger-par-2026-06-29"]
    assert ger.home_team == "Germany"
    assert ger.away_team == "Paraguay"
    # Ninguno es player-props / more-markets / total-corners
    for s in summaries:
        assert not s.slug.endswith("player-props")
        assert not s.slug.endswith("more-markets")
        assert not s.slug.endswith("total-corners")


def test_parse_match_list_filters_excluded_slugs():
    events = [
        {"slug": "fifwc-ger-par-2026-06-29-player-props", "title": "X vs. Y",
         "markets": [{"question": "Will X vs. Y end in a draw?"}]},
        {"slug": "fifwc-ger-par-2026-06-29-more-markets", "title": "X vs. Y",
         "markets": [{"question": "X vs. Y: O/U 2.5"}]},
        {"slug": "other-prefix-match", "title": "A vs. B",
         "markets": [{"question": "Will A vs. B end in a draw?"}]},
        {"slug": "fifwc-no-draw-market", "title": "C vs. D",
         "markets": [{"question": "Will C win?"}]},
    ]
    assert parse_match_list(events, "fifwc-") == []


# --------------------------------------------------------------------------- #
# Robustez: sin more-markets
# --------------------------------------------------------------------------- #
def test_parse_match_markets_without_more(main_event, config):
    mm = parse_match_markets(main_event, None, config)
    assert mm.over_under == {}
    assert mm.btts is None
    assert mm.one_x_two["home"].price == pytest.approx(0.715, abs=0.01)
    assert mm.quality_flags == ["OK"]


def test_parse_more_markets_none():
    over_under, btts = parse_more_markets(None)
    assert over_under == {}
    assert btts is None


# --------------------------------------------------------------------------- #
# Quality flags
# --------------------------------------------------------------------------- #
def test_quality_flags_low_liquidity_and_high_spread(main_event):
    # Umbrales agresivos: la liquidez/spread reales deben gatillar flags.
    cfg = {"max_spread": 0.005, "min_liquidity": 10_000_000}
    mm = parse_match_markets(main_event, None, cfg)
    assert "LOW_LIQUIDITY" in mm.quality_flags
    assert "HIGH_SPREAD" in mm.quality_flags
    assert "OK" not in mm.quality_flags


# --------------------------------------------------------------------------- #
# Capa HTTP con client inyectado (sin red real)
# --------------------------------------------------------------------------- #
class _FakeClient:
    """Cliente falso que responde segun el slug pedido."""

    def __init__(self, main, more):
        self._main = main
        self._more = more
        self.calls = []

    def get_events(self, params):
        self.calls.append(params)
        slug = params.get("slug", "")
        if slug.endswith("-more-markets"):
            return [self._more] if self._more is not None else []
        if slug:
            return [self._main]
        return []


def test_get_match_markets_with_injected_client(main_event, more_event, config):
    client = _FakeClient(main_event, more_event)
    mm = get_match_markets("fifwc-ger-par-2026-06-29", client=client, config=config)
    assert mm.summary.home_team == "Germany"
    assert 2.5 in mm.over_under
    assert mm.btts is not None


def test_get_match_markets_tolerates_missing_more(main_event, config):
    client = _FakeClient(main_event, None)
    mm = get_match_markets("fifwc-ger-par-2026-06-29", client=client, config=config)
    assert mm.over_under == {}
    assert mm.btts is None


def test_get_match_markets_raises_when_main_missing(config):
    class _EmptyClient:
        def get_events(self, params):
            return []

    with pytest.raises(PolymarketError):
        get_match_markets("nope", client=_EmptyClient(), config=config)


def test_list_world_cup_matches_with_injected_client(events_list, config):
    full_config = dict(config)
    full_config.update({"world_cup_tag_id": 102232, "match_slug_prefix": "fifwc-"})

    class _ListClient:
        def __init__(self):
            self.served = False

        def get_events(self, params):
            # Una sola pagina; la lista tiene <100 -> corta el paginado.
            if self.served:
                return []
            self.served = True
            return events_list

    matches = list_world_cup_matches(client=_ListClient(), config=full_config)
    assert len(matches) == 14
    assert all(isinstance(m, MatchSummary) for m in matches)


# --------------------------------------------------------------------------- #
# Estado live: parse_live_state sobre los 4 fixtures del partido
# --------------------------------------------------------------------------- #
def test_parse_live_state_main_in_play():
    event = _load("wc_match_main.json")[0]
    live = parse_live_state(event)
    assert isinstance(live, LiveState)
    assert live.status == "in"
    assert live.is_live is True
    assert live.minute == 13
    assert (live.home_score, live.away_score) == (0, 0)


def test_parse_live_state_live_scored():
    event = _load("wc_match_live_scored.json")[0]
    live = parse_live_state(event)
    assert live.status == "in"
    assert live.is_live is True
    assert live.minute == 70
    assert (live.home_score, live.away_score) == (1, 1)


def test_parse_live_state_pre():
    event = _load("wc_match_pre.json")[0]
    live = parse_live_state(event)
    assert live.status == "pre"
    assert live.is_live is False
    assert live.minute is None
    assert live.home_score is None
    assert live.away_score is None


def test_parse_live_state_post():
    event = _load("wc_match_post.json")[0]
    live = parse_live_state(event)
    assert live.status == "post"
    assert live.is_live is False
    assert (live.home_score, live.away_score) == (2, 1)


def test_parse_live_state_halftime():
    # Defensivo: period HT -> 'halftime'.
    live = parse_live_state({"live": True, "period": "HT", "score": "1-0", "elapsed": "45"})
    assert live.status == "halftime"
    assert live.is_live is True
    assert (live.home_score, live.away_score) == (1, 0)


def test_parse_live_state_empty_event():
    live = parse_live_state({})
    assert live.status == "pre"
    assert live.is_live is False
    assert live.minute is None


def test_match_markets_populates_live(main_event, more_event, config):
    mm = parse_match_markets(main_event, more_event, config)
    assert isinstance(mm.live, LiveState)
    assert mm.live.status == "in"
    assert mm.live.is_live is True
    assert mm.live.minute == 13
    assert (mm.live.home_score, mm.live.away_score) == (0, 0)


def test_get_match_markets_live_via_injected_client(more_event, config):
    live_main = _load("wc_match_live_scored.json")[0]
    client = _FakeClient(live_main, more_event)
    mm = get_match_markets("fifwc-live", client=client, config=config)
    assert mm.live.status == "in"
    assert (mm.live.home_score, mm.live.away_score) == (1, 1)
    assert mm.live.minute == 70


# --------------------------------------------------------------------------- #
# Fallback ESPN: parse_espn_scoreboard (parser puro)
# --------------------------------------------------------------------------- #
def test_parse_espn_scoreboard_in_play():
    scoreboard = _load("espn_wc_scoreboard.json")
    live = parse_espn_scoreboard(scoreboard, "Germany", "Paraguay")
    assert live is not None
    assert live.status == "in"
    assert live.is_live is True
    assert (live.home_score, live.away_score) == (1, 1)
    # clock 3660s -> 61 min
    assert live.minute == pytest.approx(61.0, abs=0.5)


def test_parse_espn_scoreboard_not_found():
    scoreboard = _load("espn_wc_scoreboard.json")
    assert parse_espn_scoreboard(scoreboard, "Argentina", "France") is None


def test_parse_espn_scoreboard_post():
    scoreboard = _load("espn_wc_scoreboard.json")
    live = parse_espn_scoreboard(scoreboard, "Brazil", "Japan")
    assert live is not None
    assert live.status == "post"
    assert live.is_live is False
    assert (live.home_score, live.away_score) == (2, 1)


# --------------------------------------------------------------------------- #
# Smoke test live (opcional, manual) — no corre por defecto
# --------------------------------------------------------------------------- #
@pytest.mark.skip(reason="network")
def test_live_smoke():
    matches = list_world_cup_matches()
    assert isinstance(matches, list)
    if matches:
        mm = get_match_markets(matches[0].slug)
        assert isinstance(mm, MatchMarkets)
