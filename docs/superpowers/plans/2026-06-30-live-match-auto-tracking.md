# Live Match auto-refrescado — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convertir Live Match en un monitor en vivo automático del partido en análisis: auto-refresco por timer, snapshots acumulados solos, y gráficos dinámicos (win-probability + escáner de edge multi-mercado).

**Architecture:** Live Match reutiliza el modelo calibrado en Market Setup (por `slug`). Un `st.fragment(run_every=...)` sondea `pm.get_match_markets(slug)` cada N segundos, arma un snapshot puro con `logic.build_live_snapshot`, lo agrega a una serie de sesión atada al `slug`, y renderiza scoreboard + KPIs + Gráfico A + Gráfico C. Toda la matemática vive en `src/models/*` y `src/dashboard/logic.py` (puro); la página solo orquesta.

**Tech Stack:** Python, Streamlit (≥1.40, `st.fragment` nativo), Plotly, numpy/scipy. Tests con pytest + `streamlit.testing.v1.AppTest`. Sin dependencias nuevas.

**Spec:** `docs/superpowers/specs/2026-06-30-live-match-auto-tracking-design.md`

---

## File Structure

- `config.yaml` — **modificar**: nuevo bloque `live:` con `live_refresh_seconds`.
- `src/dashboard/logic.py` — **modificar**: agregar `build_live_snapshot`, `goal_markers`, `market_label`; eliminar `build_snapshot` y `forward_draw_curve` (obsoletos).
- `src/dashboard/state.py` — **modificar**: agregar `append_live_snapshot`, `get_series`, `reset_series`; eliminar `append_snapshot`/`get_snapshots`/`clear_snapshots` (obsoletos).
- `app/pages/02_live_match.py` — **reescribir**: página auto-refrescada (sin inputs manuales).
- `tests/test_dashboard_logic.py` — **modificar**: tests de las nuevas funciones puras; quitar los de `build_snapshot`/`forward_draw_curve`.
- `tests/test_live_match_page.py` — **crear**: AppTest de la página nueva.
- `tests/test_dashboard_pages.py` — **modificar**: mover/eliminar los tests live viejos.

Convención de comandos del repo: `source .venv/bin/activate` y `.venv/bin/python -m pytest`.

---

## Task 1: Config — bloque `live:`

**Files:**
- Modify: `config.yaml`

- [ ] **Step 1: Agregar el bloque `live:` al final de `config.yaml`**

```yaml
live:
  live_refresh_seconds: 30
```

- [ ] **Step 2: Verificar que carga**

Run: `.venv/bin/python -c "from src.utils.config import load_config; print(load_config(section='live'))"`
Expected: `{'live_refresh_seconds': 30}`

- [ ] **Step 3: Commit**

```bash
git add config.yaml
git commit -m "config: bloque live con live_refresh_seconds"
```

---

## Task 2: `logic.build_live_snapshot`

Función pura que, dado el modelo guardado y un `MatchMarkets` (lectura live), arma el snapshot con probabilidades 1X2 finales y edge por mercado.

**Files:**
- Modify: `src/dashboard/logic.py`
- Test: `tests/test_dashboard_logic.py`

- [ ] **Step 1: Agregar helpers de fixture e import en `tests/test_dashboard_logic.py`**

Agregar cerca de la cabecera del archivo (después de los imports existentes):

```python
import json
import os

from src.connectors import polymarket as pm

_FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
_PM_CONFIG = {"max_spread": 0.06, "min_liquidity": 500}


def _load_fix(name):
    with open(os.path.join(_FIXTURES, name), "r") as f:
        return json.load(f)


def _live_markets():
    """Germany vs Paraguay LIVE 0-0 (1H, min 13) con O/U + BTTS."""
    main = _load_fix("wc_match_main.json")[0]
    more = _load_fix("wc_match_more_markets.json")[0]
    return pm.parse_match_markets(main, more, _PM_CONFIG)


def _live_model():
    return {
        "model_type": "poisson",
        "lambda_home": 1.6,
        "lambda_away": 1.0,
        "rho": -0.13,
        "metadata": {"slug": "fifwc-ger-par"},
    }
```

- [ ] **Step 2: Escribir el test que falla**

```python
def test_build_live_snapshot_keys_and_consistency():
    snap = logic.build_live_snapshot(_live_model(), _live_markets(), CFG)

    expected = {
        "minute", "home_score", "away_score", "status",
        "model_home_prob", "model_draw_prob", "model_away_prob",
        "market_draw_price", "edge", "edges", "best_opportunity",
    }
    assert expected <= set(snap.keys())

    # Estado live del fixture principal.
    assert snap["status"] == "in"
    assert snap["home_score"] == 0 and snap["away_score"] == 0

    # Las 3 probabilidades del resultado final suman ~1.
    total = snap["model_home_prob"] + snap["model_draw_prob"] + snap["model_away_prob"]
    assert total == pytest.approx(1.0, abs=1e-6)

    # Edge del empate coherente con la definición.
    assert snap["edge"] == pytest.approx(snap["model_draw_prob"] - snap["market_draw_price"])

    # Escáner multi-mercado: al menos home/draw/away, ordenado por |edge|.
    assert len(snap["edges"]) >= 3
    abs_edges = [abs(e["edge"]) for e in snap["edges"] if e["edge"] is not None]
    assert abs_edges == sorted(abs_edges, reverse=True)

    # Mejor oportunidad = primer edge no nulo.
    assert snap["best_opportunity"]["edge"] is not None
```

- [ ] **Step 3: Run test para verificar que falla**

Run: `.venv/bin/python -m pytest tests/test_dashboard_logic.py::test_build_live_snapshot_keys_and_consistency -q`
Expected: FAIL con `AttributeError: module 'src.dashboard.logic' has no attribute 'build_live_snapshot'`

- [ ] **Step 4: Implementar `build_live_snapshot` en `src/dashboard/logic.py`**

Actualizar el import de modelos al principio del archivo:

```python
from src.models import analytics, dixon_coles, live_update, poisson
```

Agregar la función:

```python
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

    edges = analytics.model_vs_market(final_matrix, lh_rem, la_rem, market_quotes)
    best = next((e for e in edges if e["edge"] is not None), None)
    draw_price = mm.one_x_two["draw"].price

    return {
        "minute": minute,
        "home_score": h,
        "away_score": a,
        "status": live.status,
        "model_home_prob": probs["home"],
        "model_draw_prob": probs["draw"],
        "model_away_prob": probs["away"],
        "market_draw_price": draw_price,
        "edge": probs["draw"] - draw_price,
        "edges": edges,
        "best_opportunity": best,
    }
```

- [ ] **Step 5: Run test para verificar que pasa**

Run: `.venv/bin/python -m pytest tests/test_dashboard_logic.py::test_build_live_snapshot_keys_and_consistency -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/dashboard/logic.py tests/test_dashboard_logic.py
git commit -m "feat(live): build_live_snapshot (probs 1X2 + edge multi-mercado)"
```

---

## Task 3: `logic.goal_markers` y `logic.market_label`

Helpers puros para el Gráfico A (marcas de gol) y para rotular mercados (KPIs y Gráfico C).

**Files:**
- Modify: `src/dashboard/logic.py`
- Test: `tests/test_dashboard_logic.py`

- [ ] **Step 1: Escribir los tests que fallan**

```python
def test_goal_markers_detects_score_changes():
    series = [
        {"minute": 10, "home_score": 0, "away_score": 0},
        {"minute": 20, "home_score": 0, "away_score": 0},
        {"minute": 35, "home_score": 1, "away_score": 0},
        {"minute": 70, "home_score": 1, "away_score": 1},
    ]
    markers = logic.goal_markers(series)
    assert [m["minute"] for m in markers] == [35, 70]
    assert markers[0]["home_score"] == 1 and markers[0]["away_score"] == 0


def test_goal_markers_empty_and_single():
    assert logic.goal_markers([]) == []
    assert logic.goal_markers([{"minute": 5, "home_score": 0, "away_score": 0}]) == []


def test_market_label():
    assert logic.market_label("draw") == "Empate"
    assert logic.market_label("home") == "Local"
    assert logic.market_label("away") == "Visita"
    assert logic.market_label("btts") == "BTTS"
    assert logic.market_label("over_2.5") == "Over 2.5"
    assert logic.market_label("desconocido") == "desconocido"
```

- [ ] **Step 2: Run para verificar que fallan**

Run: `.venv/bin/python -m pytest tests/test_dashboard_logic.py -k "goal_markers or market_label" -q`
Expected: FAIL con `AttributeError` (funciones inexistentes)

- [ ] **Step 3: Implementar en `src/dashboard/logic.py`**

```python
_MARKET_LABELS = {"home": "Local", "draw": "Empate", "away": "Visita", "btts": "BTTS"}


def market_label(name: str) -> str:
    """Rótulo legible de un mercado canónico (home/draw/away/over_L/btts)."""
    if name in _MARKET_LABELS:
        return _MARKET_LABELS[name]
    if name.startswith("over_"):
        return f"Over {name[len('over_'):]}"
    return name


def goal_markers(series: list) -> list:
    """Puntos de la serie donde cambió el marcador (para marcar goles en el eje).

    Devuelve un dict {minute, home_score, away_score} por cada snapshot cuyo
    marcador difiere del snapshot inmediatamente anterior.
    """
    markers = []
    prev = None
    for s in series:
        score = (s["home_score"], s["away_score"])
        if prev is not None and score != prev:
            markers.append({
                "minute": s["minute"],
                "home_score": s["home_score"],
                "away_score": s["away_score"],
            })
        prev = score
    return markers
```

- [ ] **Step 4: Run para verificar que pasan**

Run: `.venv/bin/python -m pytest tests/test_dashboard_logic.py -k "goal_markers or market_label" -q`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/dashboard/logic.py tests/test_dashboard_logic.py
git commit -m "feat(live): goal_markers y market_label (helpers de los graficos)"
```

---

## Task 4: `state` — serie atada al partido

Serie de snapshots en sesión, atada al `slug`. Se reinicia al cambiar de partido.

**Files:**
- Modify: `src/dashboard/state.py`

- [ ] **Step 1: Agregar claves y funciones en `src/dashboard/state.py`**

Junto a las claves existentes:

```python
SERIES_KEY = "live_series"
SERIES_SLUG_KEY = "live_series_slug"
```

Agregar al final del archivo:

```python
def append_live_snapshot(slug: str, snapshot: dict) -> None:
    """Agrega un snapshot a la serie del partido `slug`.

    Si el slug difiere del de la serie actual, reinicia la serie (se analiza un
    partido a la vez; cambiar de partido no debe mezclar series).
    """
    if st.session_state.get(SERIES_SLUG_KEY) != slug:
        st.session_state[SERIES_KEY] = []
        st.session_state[SERIES_SLUG_KEY] = slug
    st.session_state.setdefault(SERIES_KEY, []).append(snapshot)


def get_series() -> list:
    """Devuelve la serie de snapshots live (vacía si no hay)."""
    return st.session_state.get(SERIES_KEY, [])


def reset_series() -> None:
    """Limpia la serie de snapshots live."""
    st.session_state[SERIES_KEY] = []
```

- [ ] **Step 2: Verificar que importa sin error**

Run: `.venv/bin/python -c "import ast; ast.parse(open('src/dashboard/state.py').read()); print('ok')"`
Expected: `ok`

(El comportamiento se valida con los AppTest de la Task 5; `state.py` depende de `st.session_state` y se cubre vía página, según la convención del repo.)

- [ ] **Step 3: Commit**

```bash
git add src/dashboard/state.py
git commit -m "feat(live): serie de snapshots atada al slug del partido"
```

---

## Task 5: Reescribir la página + AppTest

Reescritura completa de la página y su suite. Este commit reemplaza los inputs manuales por el panel auto-refrescado y actualiza los tests en el mismo paso (verde al commitear).

**Files:**
- Rewrite: `app/pages/02_live_match.py`
- Create: `tests/test_live_match_page.py`
- Modify: `tests/test_dashboard_pages.py` (quitar los tests live viejos)

- [ ] **Step 1: Reemplazar TODO el contenido de `app/pages/02_live_match.py`**

```python
"""Live Match: monitor en vivo auto-refrescado del partido en análisis.

Reutiliza el modelo calibrado en Market Setup (por slug), sondea Polymarket en
un st.fragment(run_every=...), acumula snapshots en una serie de sesión y
renderiza scoreboard + KPIs + Gráfico A (win-probability) + Gráfico C (escáner
de edge multi-mercado). Sin inputs manuales; nada de matemática inline.
"""
import os
import sys
from datetime import datetime

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import plotly.graph_objects as go
import streamlit as st

from src.connectors import polymarket as pm
from src.dashboard import logic, state
from src.utils.config import load_config

st.set_page_config(page_title="Live Match", page_icon="🟢")

cfg = load_config()
_REFRESH = int(load_config(section="live").get("live_refresh_seconds", 30))

st.title("🟢 Live Match")

# --- Guard: requiere modelo calibrado en Market Setup ----------------------
model = state.get_model()
if model is None:
    st.warning("Calibra primero en Market Setup")
    st.stop()

meta = model["metadata"]
slug = meta.get("slug")
home_team = meta.get("home_team", "Local")
away_team = meta.get("away_team", "Visita")
st.subheader(meta.get("match_name", "Partido"))

# --- Controles -------------------------------------------------------------
c1, c2, c3 = st.columns([2, 1, 1])
with c1:
    auto_on = st.toggle(f"Auto-refresco (cada {_REFRESH}s)", value=True, key="live_auto")
with c2:
    st.button("↻ Actualizar ahora", key="live_refresh_now")  # el click ya re-corre el fragmento
with c3:
    if st.button("🗑 Reiniciar serie", key="live_reset_series"):
        state.reset_series()

# run_every se apaga si Auto está OFF o si el partido ya terminó (auto-stop).
_last_status = st.session_state.get("live_last_status")
run_every = None if (_last_status == "post" or not auto_on) else f"{_REFRESH}s"


def _period_label(status, minute):
    if status == "halftime":
        return "Entretiempo"
    if minute is not None and minute <= 45:
        return "1er tiempo"
    return "2do tiempo"


def _scoreboard(live):
    h = live.home_score if live.home_score is not None else 0
    a = live.away_score if live.away_score is not None else 0
    if live.status == "post":
        st.error(f"🏁 Finalizado · {home_team} {h} – {a} {away_team}")
    elif live.status in ("in", "halftime"):
        minute_txt = "—" if live.minute is None else f"{live.minute:.0f}'"
        st.success(
            f"🟢 EN VIVO · min {minute_txt} · {home_team} {h} – {a} {away_team} · "
            f"{_period_label(live.status, live.minute)}"
        )
    else:
        st.info(f"🔵 Aún no comienza · {home_team} vs {away_team}")


def _render_kpis(snap):
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric(f"P(gana {home_team})", f"{snap['model_home_prob']:.3f}")
    k2.metric("P(empate)", f"{snap['model_draw_prob']:.3f}")
    k3.metric(f"P(gana {away_team})", f"{snap['model_away_prob']:.3f}")
    k4.metric("Edge empate", f"{snap['edge']:+.3f}")
    best = snap.get("best_opportunity")
    if best is not None:
        k5.metric("Mejor oportunidad", logic.market_label(best["market"]), f"{best['edge']:+.3f}")
    else:
        k5.metric("Mejor oportunidad", "—")


def _render_chart_a(series):
    st.markdown("**📈 A · Probabilidades del resultado final en el tiempo**")
    if not series:
        st.info("Esperando datos en vivo…")
        return
    mins = [s["minute"] for s in series]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=mins, y=[s["model_home_prob"] for s in series],
                             mode="lines+markers", name=f"Gana {home_team}",
                             line=dict(color="#4C78A8")))
    fig.add_trace(go.Scatter(x=mins, y=[s["model_draw_prob"] for s in series],
                             mode="lines+markers", name="Empate",
                             line=dict(color="#E1A33A")))
    fig.add_trace(go.Scatter(x=mins, y=[s["model_away_prob"] for s in series],
                             mode="lines+markers", name=f"Gana {away_team}",
                             line=dict(color="#C0504D")))
    for mk in logic.goal_markers(series):
        fig.add_vline(x=mk["minute"], line_dash="dash", line_color="gray")
        fig.add_annotation(x=mk["minute"], y=1.0,
                           text=f"⚽ {mk['home_score']}-{mk['away_score']}",
                           showarrow=False, font=dict(size=10))
    fig.update_layout(xaxis_title="Minuto", yaxis_title="Probabilidad", yaxis_range=[0, 1])
    st.plotly_chart(fig, use_container_width=True)


def _render_chart_c(snap):
    st.markdown("**🎯 C · Escáner de edge por mercado (ordenado por |edge|)**")
    rows = [e for e in snap.get("edges", []) if e["edge"] is not None]
    if not rows:
        st.info("Sin mercados comparables aún.")
        return
    labels = [logic.market_label(e["market"]) for e in rows][::-1]
    values = [e["edge"] for e in rows][::-1]
    colors = ["#4C9A6A" if v > 0 else "#C0504D" for v in values]
    fig = go.Figure(go.Bar(x=values, y=labels, orientation="h", marker_color=colors))
    fig.add_vline(x=0.0, line_color="gray")
    fig.update_layout(xaxis_title="Edge (modelo − mercado)")
    st.plotly_chart(fig, use_container_width=True)


@st.fragment(run_every=run_every)
def live_panel():
    try:
        mm = pm.get_match_markets(slug)
    except Exception as exc:  # red caída: conservar la serie, no caerse
        st.warning(f"No se pudo actualizar ahora ({exc}). Se conserva la última serie.")
        return

    live = mm.live
    _scoreboard(live)

    if live.status in ("in", "halftime") and live.minute is not None:
        state.append_live_snapshot(slug, logic.build_live_snapshot(model, mm, cfg))
    elif live.status == "post":
        st.caption("Partido finalizado: auto-refresco detenido.")

    series = state.get_series()
    st.caption(f"Última actualización: {datetime.now():%H:%M:%S} · {len(series)} snapshots")
    if series:
        _render_kpis(series[-1])
    st.divider()
    _render_chart_a(series)
    _render_chart_c(series[-1] if series else {})

    # Auto-stop / re-sync del timer: si el estado actual cambia lo que debería ser
    # run_every (p. ej. el partido pasó a 'post', o se reanudó), re-corre la app
    # una vez para recomputar run_every. Converge porque el outer lee el estado ya
    # actualizado en la próxima pasada.
    st.session_state["live_last_status"] = live.status
    desired_off = (live.status == "post") or (not auto_on)
    if desired_off != (run_every is None):
        st.rerun()


live_panel()
```

- [ ] **Step 2: Crear `tests/test_live_match_page.py`**

```python
"""AppTest de la página Live Match auto-refrescada.

Sin red: se parsea un MatchMarkets desde fixtures reales y se mockea
pm.get_match_markets. El modelo se pre-siembra en session_state como lo haría
Market Setup. Cada at.run() ejecuta el fragmento una vez (simula un 'tick').
"""
import json
import os
from unittest.mock import patch

import streamlit as st
from streamlit.testing.v1 import AppTest

from src.connectors import polymarket as pm
from src.dashboard import state

LIVE = "app/pages/02_live_match.py"
_FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
_PM_CONFIG = {"max_spread": 0.06, "min_liquidity": 500}


def _load(name):
    with open(os.path.join(_FIXTURES, name), "r") as f:
        return json.load(f)


def _markets(main_name, more_name=None):
    main = _load(main_name)[0]
    more = _load(more_name)[0] if more_name else None
    return pm.parse_match_markets(main, more, _PM_CONFIG)


def _model(slug="fifwc-ger-par"):
    return {
        "metadata": {
            "home_team": "Germany", "away_team": "Paraguay",
            "match_name": "Germany vs Paraguay", "model_type": "poisson",
            "slug": slug,
        },
        "model_type": "poisson",
        "lambda_home": 1.6, "lambda_away": 1.0, "rho": -0.13,
        "market_probs": {"home": 0.5, "draw": 0.3, "away": 0.2},
        "config": {},
    }


def _all_text(at):
    chunks = []
    for coll in (at.markdown, at.caption, at.success, at.info, at.warning, at.error, at.subheader):
        for el in coll:
            chunks.append(str(getattr(el, "value", "")))
    return "\n".join(chunks)


def test_live_without_model_shows_warning():
    st.cache_data.clear()
    at = AppTest.from_file(LIVE).run()
    assert not at.exception
    assert any("Calibra primero" in w.value for w in at.warning)


def test_live_renders_scoreboard_kpis_and_charts():
    st.cache_data.clear()
    markets = _markets("wc_match_main.json", "wc_match_more_markets.json")  # LIVE 0-0 min 13
    with patch.object(pm, "get_match_markets", return_value=markets):
        at = AppTest.from_file(LIVE)
        at.default_timeout = 30
        at.session_state[state.MODEL_KEY] = _model()
        at.run()
        assert not at.exception

        text = _all_text(at)
        assert "EN VIVO" in text
        assert "13" in text  # minuto del fixture

        # KPIs: las 3 probabilidades del modelo presentes.
        labels = [str(getattr(m, "label", "")) for m in at.metric]
        assert any("P(gana Germany)" in l for l in labels)
        assert any("P(empate)" in l for l in labels)
        assert any("P(gana Paraguay)" in l for l in labels)

        # Gráfico A + Gráfico C.
        assert len(at.plotly_chart) >= 2

        # Se acumuló un snapshot.
        assert len(state.get_series()) >= 1


def test_live_accumulates_and_marks_goal():
    st.cache_data.clear()
    m_00 = _markets("wc_match_main.json", "wc_match_more_markets.json")   # 0-0 min 13
    m_11 = _markets("wc_match_live_scored.json")                          # 1-1 min 70
    with patch.object(pm, "get_match_markets") as mock_get:
        at = AppTest.from_file(LIVE)
        at.default_timeout = 30
        at.session_state[state.MODEL_KEY] = _model()

        mock_get.return_value = m_00
        at.run()
        mock_get.return_value = m_11
        at.run()

        series = state.get_series()
        assert len(series) == 2
        assert (series[-1]["home_score"], series[-1]["away_score"]) == (1, 1)


def test_live_series_resets_on_match_change():
    st.cache_data.clear()
    markets = _markets("wc_match_main.json", "wc_match_more_markets.json")
    with patch.object(pm, "get_match_markets", return_value=markets):
        at = AppTest.from_file(LIVE)
        at.default_timeout = 30
        at.session_state[state.MODEL_KEY] = _model(slug="fifwc-aaa")
        at.run()
        assert len(state.get_series()) == 1

        # Cambia el partido en análisis (otro slug) -> la serie se reinicia.
        at.session_state[state.MODEL_KEY] = _model(slug="fifwc-bbb")
        at.run()
        assert len(state.get_series()) == 1  # no acumuló sobre el anterior


def test_live_post_shows_final_and_stops_accumulating():
    st.cache_data.clear()
    markets = _markets("wc_match_post.json")  # VFT 2-1
    with patch.object(pm, "get_match_markets", return_value=markets):
        at = AppTest.from_file(LIVE)
        at.default_timeout = 30
        at.session_state[state.MODEL_KEY] = _model()
        at.run()
        assert not at.exception

        text = _all_text(at)
        assert "Finalizado" in text
        assert "2 – 1" in text
        # En post no se agregan snapshots.
        assert len(state.get_series()) == 0
```

- [ ] **Step 3: Quitar los tests live viejos de `tests/test_dashboard_pages.py`**

Eliminar las funciones `test_live_without_model_shows_warning` y
`test_live_with_model_registers_snapshot` (ahora viven en `test_live_match_page.py`),
junto con el helper `_valid_model` y la constante `LIVE` si quedan sin uso en ese
archivo. Mantener los tests de Home y Market Setup intactos.

- [ ] **Step 4: Run de la suite de la página live**

Run: `.venv/bin/python -m pytest tests/test_live_match_page.py -q`
Expected: PASS (5 tests)

- [ ] **Step 5: Run de la suite de páginas (sin los viejos live)**

Run: `.venv/bin/python -m pytest tests/test_dashboard_pages.py -q`
Expected: PASS (sin errores de import ni de keys inexistentes)

- [ ] **Step 6: Commit**

```bash
git add app/pages/02_live_match.py tests/test_live_match_page.py tests/test_dashboard_pages.py
git commit -m "feat(live): pagina Live Match auto-refrescada (scoreboard + KPIs + graficos A y C)"
```

---

## Task 6: Limpieza de código obsoleto

Quita lo que la página vieja usaba y ya no se usa: `forward_draw_curve` y
`build_snapshot` en `logic.py`, y `append_snapshot`/`get_snapshots`/`clear_snapshots`
+ `SNAPSHOTS_KEY` en `state.py`, con sus tests.

**Files:**
- Modify: `src/dashboard/logic.py`
- Modify: `src/dashboard/state.py`
- Modify: `tests/test_dashboard_logic.py`

- [ ] **Step 1: Confirmar que no quedan usos**

Run: `grep -rn "forward_draw_curve\|build_snapshot\|append_snapshot\|get_snapshots\|clear_snapshots\|SNAPSHOTS_KEY" app/ src/ tests/`
Expected: solo aparecen en las definiciones de `logic.py`/`state.py` y en los tests de `test_dashboard_logic.py` que se van a borrar (ningún uso en `app/`).

- [ ] **Step 2: Eliminar de `src/dashboard/logic.py`**

Borrar las funciones `build_snapshot` y `forward_draw_curve` por completo.
Conservar `compute_edge` y `describe_edge` (siguen usándose para el KPI del empate).

- [ ] **Step 3: Eliminar de `src/dashboard/state.py`**

Borrar `SNAPSHOTS_KEY`, `append_snapshot`, `get_snapshots`, `clear_snapshots`.
Conservar `save_model`/`get_model` y las funciones de serie de la Task 4.
En `reset_session`, reemplazar la referencia a `SNAPSHOTS_KEY` por `SERIES_KEY`:

```python
def reset_session() -> None:
    """Limpia el modelo y la serie de snapshots de la sesión."""
    st.session_state.pop(MODEL_KEY, None)
    st.session_state[SERIES_KEY] = []
```

- [ ] **Step 4: Eliminar de `tests/test_dashboard_logic.py`**

Borrar `test_build_snapshot_keys_and_consistency` y
`test_forward_draw_curve_slice_and_endpoint` (cubrían funciones eliminadas).
Conservar los tests de `compute_edge`, `describe_edge`, `build_live_snapshot`,
`goal_markers` y `market_label`. Quitar el import de `live_update` si quedó sin
uso tras borrar esos tests.

- [ ] **Step 5: Run de la suite de lógica**

Run: `.venv/bin/python -m pytest tests/test_dashboard_logic.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/dashboard/logic.py src/dashboard/state.py tests/test_dashboard_logic.py
git commit -m "refactor(live): elimina forward_draw_curve/build_snapshot y snapshots manuales obsoletos"
```

---

## Task 7: Docs + verificación final

**Files:**
- Modify: `CLAUDE.md`
- Modify: `docs/superpowers/specs/2026-06-30-live-match-auto-tracking-design.md`

- [ ] **Step 1: Actualizar `CLAUDE.md`**

En la sección "Estado actual", agregar un bloque para el nuevo entregable, por
ejemplo tras el Entregable D:

```markdown
**Entregable E: Live Match auto-refrescado** ✅. La página dejó de ser manual:
reutiliza el modelo de Market Setup (por `slug`), sondea Polymarket en un
`st.fragment(run_every=...)`, acumula snapshots solos y muestra **Gráfico A**
(win-probability: P local/empate/visita del resultado final en el tiempo, con
marcas de gol) y **Gráfico C** (escáner de edge multi-mercado). xG diferido
(sin fuente live gratuita confiable). Diseño:
`docs/superpowers/specs/2026-06-30-live-match-auto-tracking-design.md`.
```

Actualizar también la línea de `src/dashboard/` en la sección Estructura si hace
falta (mencionar `build_live_snapshot`, serie en `state.py`).

- [ ] **Step 2: Marcar el spec como implementado**

En la cabecera del spec, cambiar `**Estado:** aprobado ...` por
`**Estado:** implementado (2026-06-30).`

- [ ] **Step 3: Correr TODA la suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS (todos los tests, incluida la suite live nueva). 0 fallos.

- [ ] **Step 4: Smoke manual opcional del dashboard**

Run: `.venv/bin/python -m streamlit run app/dashboard.py`
Expected: Market Setup calibra un partido; en Live Match aparece el scoreboard,
los KPIs y los Gráficos A y C; con Auto ON la página se refresca sola.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md docs/superpowers/specs/2026-06-30-live-match-auto-tracking-design.md
git commit -m "docs: Entregable E (Live Match auto-refrescado) + spec implementado"
```

---

## Notas de verificación (self-review)

- **Cobertura del spec:** captura auto (Task 5, `st.fragment`), xG diferido (no se
  introduce ningún input/fuente de xG), reutiliza modelo por slug (Task 5),
  serie atada al slug + reset (Task 4 + test en Task 5), scoreboard/KPIs/controles
  (Task 5), Gráfico A win-probability + marcas de gol (Task 3 + Task 5), Gráfico C
  escáner edge (Task 2 `edges` + Task 5), auto-stop en post (Task 5), robustez de
  red (Task 5, try/except), config del intervalo (Task 1). Cleanup de obsoletos
  (Task 6). Docs (Task 7).
- **Sin placeholders:** todo el código está completo e inline.
- **Consistencia de tipos:** `build_live_snapshot` devuelve las claves que la
  página y los tests consumen (`model_*_prob`, `edge`, `edges`, `best_opportunity`,
  `status`, `home_score`, `away_score`, `minute`, `market_draw_price`).
  `append_live_snapshot(slug, snapshot)` / `get_series()` / `reset_series()`
  usadas con esa firma exacta en la página y los tests.
```
