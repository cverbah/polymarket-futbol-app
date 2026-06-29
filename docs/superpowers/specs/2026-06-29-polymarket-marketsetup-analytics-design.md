# Diseño — Entregable C: Market Setup conectado a Polymarket + analítica rica

> **Fecha:** 2026-06-29
> **Alcance:** Reescribir la página Market Setup para que **no tenga inputs
> manuales**: el usuario selecciona un partido del **Mundial 2026** desde un
> selector poblado en vivo desde Polymarket, y la página carga precios, calibra
> el modelo y despliega una **analítica rica** (incluyendo Modelo vs Mercado).
> Solo lectura de Polymarket (sin envío de órdenes).

---

## 1. Decisiones tomadas (brainstorming)

| # | Decisión | Elección |
|---|----------|----------|
| 1 | Selección de partido | **Selector** de partidos (no URL, no manual) |
| 2 | Foco | **Mundial 2026** (FIFA World Cup) |
| 3 | Motor de analítica | **Analítico exacto** desde la matriz (no Monte Carlo) |
| 4 | Catálogo de analítica | Set completo (ver §4.2), con **Modelo vs Mercado** como pieza central |

---

## 2. Realidad de los datos de Polymarket (investigada, no asumida)

API pública **Gamma** (`https://gamma-api.polymarket.com`), sin API key, solo lectura.

**Estructura de un partido del Mundial** (verificada con datos reales):
- **Evento principal** — slug `fifwc-{LOC}-{VIS}-{YYYY-MM-DD}` (ej.
  `fifwc-ger-par-2026-06-29`). Contiene 3 mercados binarios Yes/No:
  - `"Will {Local} win on {fecha}?"` → precio Yes = P(gana local)
  - `"Will {Local} vs. {Visita} end in a draw?"` → precio Yes = P(empate)
  - `"Will {Visita} win on {fecha}?"` → precio Yes = P(gana visita)
- **Evento "More Markets"** — slug `{slug-principal}-more-markets`. Contiene
  el **O/U total** del partido (`"{match}: O/U 2.5"` → Over/Under) para líneas
  0.5–8.5, y **BTTS** (`"{match}: Both Teams to Score"` → Yes/No). También trae
  O/U por equipo y por tiempo (fuera de alcance por ahora).
- Eventos `-player-props` y `-total-corners` existen pero **no se usan**.

**Descubrimiento:** los partidos del Mundial están bajo el **tag `102232`
("FIFA World Cup")** y el slug empieza con `fifwc-`. ⚠️ El tag `102350`
("2026 FIFA World Cup") solo tiene props/campeón — **no** los partidos 1X2.

**Calidad de dato:** los partidos grandes del Mundial son **líquidos y de spread
ajustado** (ej. Germany–Paraguay: spread 0.01, liquidez cientos de miles USD).
Aun así, el diseño debe medir y mostrar liquidez/spread por mercado, porque no
todos los partidos serán igual de líquidos.

**Fixtures capturados** (datos reales, para tests sin red), en `tests/fixtures/`:
- `wc_match_main.json` — evento principal 1X2 (Germany vs Paraguay).
- `wc_match_more_markets.json` — O/U + BTTS del mismo partido.
- `wc_events_list.json` — lista de 14 partidos 1X2 del Mundial (recortada).

---

## 3. Estructura del proyecto

```text
src/connectors/
├── __init__.py
└── polymarket.py        # cliente read-only Gamma API: descubrir + leer mercados
src/models/
└── analytics.py         # derivaciones analíticas puras desde la matriz
app/pages/01_market_setup.py   # REESCRITA: selector + auto-carga + analítica
tests/
├── fixtures/            # JSON reales de Polymarket (ya capturados)
├── test_polymarket_connector.py   # parsing con fixtures (sin red)
└── test_analytics.py              # métricas puras
```

El motor del Entregable A (`poisson`, `dixon_coles`, `calibration`,
`live_update`) **no se modifica**. El dict del modelo guardado en
`session_state` se mantiene **compatible** con la página Live Match.

---

## 4. Componentes

### 4.1 `src/connectors/polymarket.py` (read-only)

Dataclasses:

```python
@dataclass
class MarketQuote:
    name: str            # "home" | "draw" | "away" | "over_2_5" | "btts" | ...
    price: float         # precio mid (outcomePrices del lado "Yes"/"Over")
    best_bid: float | None
    best_ask: float | None
    spread: float | None
    liquidity: float | None

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
    one_x_two: dict          # {"home": MarketQuote, "draw": ..., "away": ...}
    over_under: dict         # {2.5: MarketQuote, ...} (líneas totales disponibles)
    btts: MarketQuote | None
    quality_flags: list[str] # OK / LOW_LIQUIDITY / HIGH_SPREAD por mercado
```

Funciones:
- `list_world_cup_matches(client=...) -> list[MatchSummary]`
  Pagina `GET /events?closed=false&tag_id=102232&order=startDate&ascending=true`,
  filtra a slugs `fifwc-*` que **no** terminen en
  `player-props`/`more-markets`/`total-corners` y que tengan el mercado
  "end in a draw". Parsea equipos del título `"{Local} vs. {Visita}"`.
- `get_match_markets(slug, client=...) -> MatchMarkets`
  `GET /events?slug={slug}` (1X2) + `GET /events?slug={slug}-more-markets`
  (O/U + BTTS; tolera 404/empty). Identifica local/visita por el orden del
  título; mapea precios; computa flags de calidad por umbral.
- **HTTP aislado** detrás de una función/objeto inyectable (`client`) para poder
  testear el parsing con fixtures y mockear en la página. Usa `requests` o
  `urllib`; timeouts; errores → excepción clara `PolymarketError`.

Las **funciones de parsing** (de JSON crudo → dataclasses) son **puras** y se
testean con los fixtures, separadas de las llamadas de red.

Umbrales de calidad (configurables en `config.yaml`, sección nueva `polymarket:`):
`max_spread: 0.06`, `min_liquidity: 500`.

### 4.2 `src/models/analytics.py` (puro, exacto)

Recibe la matriz de marcadores y los lambdas; devuelve el catálogo:

- `expected_goals(lambda_home, lambda_away) -> dict` (local, visita, total).
- `one_x_two(matrix) -> dict` (reusa `poisson.outcome_probs`).
- `double_chance(probs) -> dict` (1X, 12, X2).
- `total_goals_distribution(matrix, up_to=5) -> dict` (P de 0,1,2,3,4,5+).
- `over_under(matrix, line) -> dict` (P(over), P(under)) para 0.5/1.5/2.5/3.5/4.5.
- `btts(matrix) -> dict` (yes/no) — P(local≥1 y visita≥1).
- `clean_sheets(matrix) -> dict` (P(local valla invicta), P(visita valla invicta)).
- `first_to_score(lambda_home, lambda_away) -> dict`
  `p_no_goals = exp(-(λh+λa))`; `p_home = (1-p_no_goals)*λh/(λh+λa)`;
  `p_away = (1-p_no_goals)*λa/(λh+λa)`.
- `winning_margin(matrix) -> dict` (P gana local por 1/2/3+, ídem visita, empate).
- `top_scores(matrix, n)` (reusa el existente).
- `model_vs_market(matrix, lambda_home, lambda_away, match_markets) -> list`
  Para **cada** mercado disponible en `match_markets` (home/draw/away, cada O/U
  total, BTTS) arma `{market, model_prob, market_price, edge}` y ordena por
  |edge| descendente. **Pieza central.**

Todas suman a 1 donde corresponde; sin estado; sin red.

### 4.3 `app/pages/01_market_setup.py` (reescrita)

Flujo, sin ningún input numérico manual:
1. **Selector** (`st.selectbox`) poblado con `list_world_cup_matches()`
   (cacheado con `st.cache_data`, TTL ~120s; botón "Actualizar lista").
   Cada opción: `"{Local} vs {Visita} — {fecha} (liq ${...})"`.
2. Al elegir: `get_match_markets(slug)` → muestra **precios + calidad** (spread,
   liquidez, flags). Si el partido es ilícito (flags), aviso destacado.
3. **Modelo:** selector chico, **default Dixon-Coles**; Poisson opcional.
   Calibra con 1X2; si hay O/U 2.5 total, lo pasa para **liberar `rho`**.
4. **Guarda** el modelo en `session_state` (formato compatible con Live).
5. **Despliega** el catálogo de §4.2 en secciones, y la tabla **Modelo vs
   Mercado** destacada (con color por signo del edge). Gráficos Plotly donde
   aporten (ej. distribución de goles, O/U por línea modelo-vs-mercado).

### 4.4 `config.yaml` — sección nueva

```yaml
polymarket:
  gamma_base_url: "https://gamma-api.polymarket.com"
  world_cup_tag_id: 102232
  match_slug_prefix: "fifwc-"
  request_timeout_seconds: 15
  list_cache_ttl_seconds: 120
  max_spread: 0.06
  min_liquidity: 500
```

---

## 5. Flujo de datos

```text
Selector:
  list_world_cup_matches() -> [MatchSummary]  (cacheado)
Selección:
  get_match_markets(slug) -> MatchMarkets (1X2 + O/U + BTTS + calidad)
    -> normalize_prices(home,draw,away) -> target
    -> calibrate(target, model, over_2_5_price si existe) -> lambdas (+rho)
    -> save_model(...)  (compatible con Live Match)
    -> score_matrix -> analytics.* + analytics.model_vs_market(..., MatchMarkets)
```

---

## 6. Testing

### 6.1 Connector (`tests/test_polymarket_connector.py`)
- **Parsing con fixtures** (sin red): `get_match_markets` sobre
  `wc_match_main.json` + `wc_match_more_markets.json` → identifica local/visita
  correctamente (Germany/Paraguay), precios 1X2 (~0.715/0.195/0.085), O/U 2.5
  total (~0.495), BTTS (~0.415), y flags de calidad (este partido = OK).
- `list_world_cup_matches` sobre `wc_events_list.json` → 14 partidos, filtra
  player-props/more-markets, parsea equipos.
- Inyección del `client`/JSON para no tocar la red. Un smoke test **live**
  marcado con `@pytest.mark.skip`/`network` (opcional, manual).

### 6.2 Analítica (`tests/test_analytics.py`)
- Cada métrica suma 1 donde corresponde; BTTS, clean sheets, first_to_score
  (incluye caso sin goles), over/under monótono creciente al bajar la línea,
  winning_margin consistente con 1X2.
- `model_vs_market`: edge = model − market con signo correcto; ordena por |edge|.

### 6.3 Página (AppTest)
- Mockea `polymarket.list_world_cup_matches` y `get_match_markets` con los
  fixtures (sin red); selecciona un partido; verifica que calibra, guarda modelo
  compatible y renderiza la tabla Modelo vs Mercado, sin excepción.

### 6.4 Verificación manual (end-to-end real)
- Levantar el dashboard y, contra Polymarket **en vivo**, seleccionar un partido
  real del Mundial y revisar precios, calibración y Modelo vs Mercado.

---

## 7. Fuera de alcance
Envío de órdenes; mejoras a Live Match; O/U por equipo y por tiempo; corners;
player props; persistencia SQLite; Monte Carlo; backtesting.
