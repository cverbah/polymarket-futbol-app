# Polymarket Football Trading Agent

Herramienta de **análisis y paper trading** para mercados de fútbol en
[Polymarket](https://polymarket.com). Toma los precios de Polymarket → los
traduce a un modelo probabilístico (Poisson / Dixon-Coles) → lo actualiza en
vivo con minuto, marcador, xG y eventos, para detectar si un outcome
(especialmente el **empate**) está caro o barato respecto al mercado.

> ⚠️ **No es un bot de ejecución automática.** Es una herramienta de análisis y
> simulación. La ejecución con dinero real es una fase muy posterior y requiere
> backtesting + paper trading positivos primero.

## ¿Cómo funciona?

1. **Modelo de probabilidades** (Poisson / Dixon-Coles): a partir de los precios
   1X2 del mercado se calibran los goles esperados (λ) de cada equipo.
2. **Analítica rica**: distribución de goles, Over/Under por línea, BTTS, clean
   sheets, primer gol, margen, doble oportunidad, top scores, y una tabla
   **Modelo vs Mercado** con el *edge* por mercado.
3. **Time-aware**: la página detecta el estado del partido desde Polymarket
   (pre / live / post) y se adapta. En vivo calibra los goles *restantes*
   condicionados al marcador actual para producir una proyección final.

## Estado del proyecto

| Entregable | Descripción | Estado |
|-----------|-------------|--------|
| **A** | Motor de probabilidades (núcleo matemático puro) | ✅ |
| **B** | Dashboard manual en Streamlit (Home / Market Setup / Live Match) | ✅ |
| **C** | Market Setup conectado a Polymarket + analítica rica | ✅ |
| **D** | Market Setup time-aware (estados pre / live / post) | ✅ |

Pendientes (entregables posteriores): xG live + edge real, mejoras a Live Match,
estrategia/EV/señales, storage SQLite, paper trading y backtesting.

Specs de diseño detallados en [`docs/superpowers/specs/`](docs/superpowers/specs/)
y el spec maestro en
[`polymarket_football_trading_agent_spec.md`](polymarket_football_trading_agent_spec.md).

## Estructura

```text
src/models/      poisson.py, dixon_coles.py, calibration.py, live_update.py, analytics.py
src/connectors/  polymarket.py (Gamma API read-only: descubrir partidos + leer mercados)
src/dashboard/   logic.py (puro), state.py (session_state)
src/utils/       validation.py, config.py
app/             dashboard.py + pages/01_market_setup.py + pages/02_live_match.py
notebooks/       poisson_sandbox.ipynb (demo Argentina vs Cabo Verde)
tests/           test_*.py + fixtures/ (JSON reales de Polymarket para tests sin red)
config.yaml      bloques `model:` y `polymarket:`
```

## Instalación

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Uso

Correr los tests:

```bash
.venv/bin/python -m pytest -q
```

Levantar el dashboard:

```bash
.venv/bin/python -m streamlit run app/dashboard.py
```

## Configuración

Todos los parámetros del modelo y del conector viven en
[`config.yaml`](config.yaml) (no se hardcodean en el código). El conector usa la
**Gamma API pública de Polymarket** en modo *read-only*; no requiere
credenciales.

## Stack

Python · numpy · scipy · Streamlit · Plotly · PyYAML · requests · pytest

## Seguridad

- Las credenciales (cuando hagan falta en fases futuras) van en `.env`, **nunca**
  en el código ni en git.
- `.env`, `.venv/`, bases de datos y datos crudos están en `.gitignore`.
