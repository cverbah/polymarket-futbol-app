"""Conector read-only a la Gamma API de Polymarket (Mundial 2026).

Solo lectura: descubre partidos del Mundial y lee sus mercados (1X2, O/U total
y BTTS). El parsing JSON->dataclasses es **puro** y se testea con fixtures sin
red; la capa HTTP esta aislada en `GammaClient` para poder inyectarse/mockear.

Ver spec: docs/superpowers/specs/2026-06-29-polymarket-marketsetup-analytics-design.md
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

import requests

from src.utils.config import load_config


# --------------------------------------------------------------------------- #
# Dataclasses
# --------------------------------------------------------------------------- #
@dataclass
class MarketQuote:
    name: str
    price: float
    best_bid: Optional[float]
    best_ask: Optional[float]
    spread: Optional[float]
    liquidity: Optional[float]


@dataclass
class MatchSummary:
    slug: str
    home_team: str
    away_team: str
    start_date: str
    total_liquidity: float
    total_volume: float


@dataclass
class MatchMarkets:
    summary: MatchSummary
    one_x_two: dict  # {"home": MarketQuote, "draw": MarketQuote, "away": MarketQuote}
    over_under: dict  # {2.5: MarketQuote, ...} con name="over_2.5" y price=Over
    btts: Optional[MarketQuote]  # name="btts", price=Yes
    quality_flags: list = field(default_factory=list)  # OK / LOW_LIQUIDITY / HIGH_SPREAD


class PolymarketError(Exception):
    """Error al hablar con la Gamma API de Polymarket."""


# --------------------------------------------------------------------------- #
# Helpers de parsing (puros)
# --------------------------------------------------------------------------- #
def _as_list(value) -> list:
    """outcomes/outcomePrices vienen como string JSON ('[\"Yes\",\"No\"]')."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return []
    if isinstance(value, list):
        return value
    return []


def _to_float(value) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _outcome_price(market: dict, outcome_name: str) -> Optional[float]:
    """Devuelve el precio del outcome dado (ej. 'Yes', 'Over') o None."""
    outcomes = _as_list(market.get("outcomes"))
    prices = _as_list(market.get("outcomePrices"))
    for i, name in enumerate(outcomes):
        if str(name).strip().lower() == outcome_name.strip().lower():
            if i < len(prices):
                return _to_float(prices[i])
    return None


def _market_liquidity(market: dict) -> Optional[float]:
    return _to_float(market.get("liquidityNum") or market.get("liquidity"))


def _quote_from_market(market: dict, name: str, outcome_name: str) -> MarketQuote:
    """Construye un MarketQuote tomando el precio del outcome indicado."""
    return MarketQuote(
        name=name,
        price=_outcome_price(market, outcome_name),
        best_bid=_to_float(market.get("bestBid")),
        best_ask=_to_float(market.get("bestAsk")),
        spread=_to_float(market.get("spread")),
        liquidity=_market_liquidity(market),
    )


def _parse_teams(title: str) -> tuple:
    """Del titulo '{Local} vs. {Visita}' extrae (home, away)."""
    if title and " vs. " in title:
        home, away = title.split(" vs. ", 1)
        return home.strip(), away.strip()
    return (title or "").strip(), ""


# --------------------------------------------------------------------------- #
# Parsing puro: JSON crudo -> dataclasses
# --------------------------------------------------------------------------- #
def parse_match_summary(event_json: dict) -> MatchSummary:
    """Resumen de un partido a partir del evento principal."""
    home, away = _parse_teams(event_json.get("title", ""))
    return MatchSummary(
        slug=event_json.get("slug", ""),
        home_team=home,
        away_team=away,
        start_date=event_json.get("startDate", ""),
        total_liquidity=_to_float(event_json.get("liquidity")) or 0.0,
        total_volume=_to_float(event_json.get("volume")) or 0.0,
    )


def parse_main_markets(event_json: dict) -> dict:
    """Mapea los 3 mercados binarios del evento principal a one_x_two.

    - draw: el mercado cuya pregunta contiene 'end in a draw'.
    - home/away: 'Will {equipo} win ...' segun que equipo aparezca.
    """
    home, away = _parse_teams(event_json.get("title", ""))
    one_x_two: dict = {}
    for market in event_json.get("markets", []):
        question = (market.get("question") or "").lower()
        if "end in a draw" in question:
            one_x_two["draw"] = _quote_from_market(market, "draw", "Yes")
        elif "win" in question:
            if home and home.lower() in question:
                one_x_two["home"] = _quote_from_market(market, "home", "Yes")
            elif away and away.lower() in question:
                one_x_two["away"] = _quote_from_market(market, "away", "Yes")
    return one_x_two


def _is_total_over_under(question: str) -> Optional[float]:
    """True si la pregunta es el O/U TOTAL del partido. Devuelve la linea.

    Acepta '{Home} vs. {Away}: O/U 2.5'. Rechaza O/U por equipo
    ('Germany O/U 2.5') y por tiempo ('1st Half O/U', '2nd Half O/U').
    """
    if ": O/U " not in question:
        return None
    lower = question.lower()
    if "1st half" in lower or "2nd half" in lower or "first half" in lower or "second half" in lower:
        return None
    # La parte despues de ': O/U ' debe ser solo la linea (ej. '2.5').
    suffix = question.split(": O/U ", 1)[1].strip()
    return _to_float(suffix)


def parse_more_markets(event_json: Optional[dict]) -> tuple:
    """Del evento '-more-markets' extrae (over_under dict, btts MarketQuote|None).

    over_under: {linea_float: MarketQuote(name='over_{linea}', price=Over)}.
    btts: MarketQuote(name='btts', price=Yes) o None.
    """
    over_under: dict = {}
    btts: Optional[MarketQuote] = None
    if not event_json:
        return over_under, btts

    for market in event_json.get("markets", []):
        question = market.get("question") or ""
        line = _is_total_over_under(question)
        if line is not None:
            over_under[line] = _quote_from_market(market, f"over_{line}", "Over")
            continue
        # BTTS total (no de tiempo): 'Both Teams to Score' sin 'in First/Second Half'.
        lower = question.lower()
        if "both teams to score" in lower and "in first half" not in lower and "in second half" not in lower:
            btts = _quote_from_market(market, "btts", "Yes")
    return over_under, btts


def _quality_flags_for(quote: Optional[MarketQuote], max_spread: float, min_liquidity: float) -> list:
    """Flags de calidad para un quote: ['OK'] o ['LOW_LIQUIDITY','HIGH_SPREAD']."""
    if quote is None:
        return []
    flags = []
    if quote.liquidity is not None and quote.liquidity < min_liquidity:
        flags.append("LOW_LIQUIDITY")
    if quote.spread is not None and quote.spread > max_spread:
        flags.append("HIGH_SPREAD")
    return flags or ["OK"]


def parse_match_markets(
    main_json: dict,
    more_json: Optional[dict],
    config: Optional[dict] = None,
) -> MatchMarkets:
    """Une evento principal + more-markets en un MatchMarkets con flags de calidad."""
    if config is None:
        config = load_config(section="polymarket")
    max_spread = float(config.get("max_spread", 0.06))
    min_liquidity = float(config.get("min_liquidity", 500))

    summary = parse_match_summary(main_json)
    one_x_two = parse_main_markets(main_json)
    over_under, btts = parse_more_markets(more_json)

    quality_flags: list = []
    quotes = list(one_x_two.values()) + list(over_under.values())
    if btts is not None:
        quotes.append(btts)
    for quote in quotes:
        for flag in _quality_flags_for(quote, max_spread, min_liquidity):
            if flag not in quality_flags:
                quality_flags.append(flag)
    # Si algun mercado fue marcado, quitamos 'OK' (solo OK si todos estan bien).
    if len(quality_flags) > 1 and "OK" in quality_flags:
        quality_flags.remove("OK")
    if not quality_flags:
        quality_flags = ["OK"]

    return MatchMarkets(
        summary=summary,
        one_x_two=one_x_two,
        over_under=over_under,
        btts=btts,
        quality_flags=quality_flags,
    )


def parse_match_list(events_json: list, slug_prefix: str = "fifwc-") -> list:
    """Filtra la lista de eventos a partidos 1X2 validos y devuelve summaries.

    Mantiene eventos cuyo slug empieza con `slug_prefix`, NO termina en
    player-props/more-markets/total-corners, y que tengan un mercado con
    'end in a draw' en la pregunta.
    """
    excluded_suffixes = ("player-props", "more-markets", "total-corners")
    summaries = []
    for event in events_json or []:
        slug = event.get("slug", "")
        if not slug.startswith(slug_prefix):
            continue
        if any(slug.endswith(suffix) for suffix in excluded_suffixes):
            continue
        questions = [(m.get("question") or "").lower() for m in event.get("markets", [])]
        if not any("end in a draw" in q for q in questions):
            continue
        summaries.append(parse_match_summary(event))
    return summaries


# --------------------------------------------------------------------------- #
# Capa HTTP (aislada e inyectable)
# --------------------------------------------------------------------------- #
class GammaClient:
    """Cliente HTTP fino sobre la Gamma API. Aislado para poder mockear."""

    def __init__(self, base_url: Optional[str] = None, timeout: Optional[float] = None,
                 config: Optional[dict] = None):
        if config is None:
            config = load_config(section="polymarket")
        self.base_url = (base_url or config.get("gamma_base_url", "https://gamma-api.polymarket.com")).rstrip("/")
        self.timeout = timeout if timeout is not None else float(config.get("request_timeout_seconds", 15))
        self._session = requests.Session()

    def get_events(self, params: dict) -> list:
        """GET /events con los params dados. Devuelve la lista JSON."""
        url = f"{self.base_url}/events"
        try:
            resp = self._session.get(url, params=params, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as exc:
            raise PolymarketError(f"Error al consultar Gamma API ({url}): {exc}") from exc
        except ValueError as exc:  # JSON invalido
            raise PolymarketError(f"Respuesta no-JSON de Gamma API ({url}): {exc}") from exc
        if not isinstance(data, list):
            return []
        return data


# --------------------------------------------------------------------------- #
# Funciones de alto nivel (red por defecto, client inyectable)
# --------------------------------------------------------------------------- #
def list_world_cup_matches(client: Optional[GammaClient] = None,
                           config: Optional[dict] = None) -> list:
    """Descubre partidos 1X2 del Mundial paginando /events por tag."""
    if config is None:
        config = load_config(section="polymarket")
    if client is None:
        client = GammaClient(config=config)

    tag_id = config.get("world_cup_tag_id", 102232)
    slug_prefix = config.get("match_slug_prefix", "fifwc-")

    matches: list = []
    seen_slugs: set = set()
    limit = 100
    offset = 0
    while True:
        params = {
            "closed": "false",
            "tag_id": tag_id,
            "order": "startDate",
            "ascending": "true",
            "limit": limit,
            "offset": offset,
        }
        page = client.get_events(params)
        if not page:
            break
        for summary in parse_match_list(page, slug_prefix):
            if summary.slug not in seen_slugs:
                seen_slugs.add(summary.slug)
                matches.append(summary)
        if len(page) < limit:
            break
        offset += limit
    return matches


def get_match_markets(slug: str, client: Optional[GammaClient] = None,
                      config: Optional[dict] = None) -> MatchMarkets:
    """Lee los mercados de un partido: evento principal + '-more-markets'."""
    if config is None:
        config = load_config(section="polymarket")
    if client is None:
        client = GammaClient(config=config)

    main_events = client.get_events({"slug": slug})
    if not main_events:
        raise PolymarketError(f"No se encontro el evento con slug '{slug}'")
    main_json = main_events[0]

    # More markets: tolera 404/empty -> over_under={}, btts=None.
    more_json = None
    try:
        more_events = client.get_events({"slug": f"{slug}-more-markets"})
        if more_events:
            more_json = more_events[0]
    except PolymarketError:
        more_json = None

    return parse_match_markets(main_json, more_json, config)
