# CLAUDE.md — Polymarket Football Trading Agent

Instrucciones para Claude al trabajar en este proyecto. Estas reglas tienen
prioridad sobre comportamientos por defecto.

## Qué es este proyecto

Herramienta de **análisis y paper trading** para mercados de fútbol en Polymarket.
Toma precios de Polymarket → los traduce a un modelo probabilístico (Poisson /
Dixon-Coles) → lo actualiza en vivo con minuto, marcador, xG y eventos, para
detectar si un outcome (especialmente el **empate**) está caro o barato.

**NO es un bot de ejecución automática.** Es una herramienta de análisis y
simulación. La ejecución de dinero real es una fase muy posterior y requiere
backtesting + paper trading positivos primero.

- Spec maestro: `polymarket_football_trading_agent_spec.md`
- Specs de diseño por entregable: `docs/superpowers/specs/`

## Estado actual

**Entregable A: motor de probabilidades** (Fase 1 del spec maestro).
Núcleo matemático puro, sin UI ni APIs externas.
Diseño: `docs/superpowers/specs/2026-06-29-poisson-probability-engine-design.md`.

Lo demás (dashboard Streamlit, conexión Polymarket, XGProvider real, estrategia/
EV/señales, storage, paper trading, backtesting) son entregables posteriores,
cada uno con su propio ciclo spec → plan → implementación.

## Estructura

```text
src/models/      poisson.py, dixon_coles.py, calibration.py, live_update.py
src/utils/       validation.py
notebooks/       poisson_sandbox.ipynb (demo Argentina vs Cabo Verde)
tests/           test_poisson.py, test_calibration.py, test_live_update.py
config.yaml      parámetros del modelo (max_goals, tau, pesos, caps, rho...)
```

## Entorno y comandos

- Entorno virtual en `.venv/`. Activar: `source .venv/bin/activate`
- Instalar deps: `pip install -r requirements.txt`
- Correr tests: `.venv/bin/python -m pytest -q`
- Correr un test: `.venv/bin/python -m pytest tests/test_poisson.py -q`

## Convenciones de código

- **Simplicidad ante todo.** Código fácil de leer; sin abstracciones innecesarias
  ni arquitecturas sobre-diseñadas. Preferir soluciones directas.
- **No reinventar la rueda.** Usar librerías estándar y confiables (numpy, scipy).
  No reimplementar lo que `scipy.stats.poisson` o `scipy.optimize` ya hacen.
- Todos los parámetros del modelo viven en `config.yaml`, no hardcodeados.
- Funciones puras y testeables: una responsabilidad clara por módulo.
- `poisson.py` y `dixon_coles.py` exponen la **misma interfaz** (intercambiables).

## TDD

Este entregable se construye con **test-driven development**: escribir el test
primero (que falle), luego la implementación mínima que lo haga pasar, refactor.
Los tests mínimos están en el spec de diseño (sección 7.2) y en el spec maestro
(sección 20).

## Seguridad (reglas estrictas)

- **NUNCA** poner API keys, tokens o secretos en el código. Van en `.env` (raíz).
- **NUNCA** commitear `.env` ni archivos `.env*`. Verificar que estén en
  `.gitignore` antes de cualquier commit.
- En ejemplos usar placeholders: `YOUR_API_KEY`, `YOUR_SECRET`.

## Idioma

Responder en español (idioma nativo del usuario). Comentarios de código pueden ir
en español o inglés, consistentes con el archivo.

## Notas de modelado clave

- Poisson independiente **subestima los empates y marcadores bajos** (0-0, 1-1).
  Por eso existe Dixon-Coles (corrección `rho` sobre esos marcadores).
- `rho` no es identificable solo con precios 1X2: por defecto se fija en
  `default_rho` (≈ −0.13) y solo se calibra si hay mercado Over/Under 2.5.
- El modelo live condiciona al **marcador actual** y modela solo los goles
  *restantes*; el xG ajusta los lambdas restantes con shrinkage contra el prior.
- Siempre usar best bid / best ask (no last price) cuando se llegue a la capa de
  mercado/estrategia — relevante para entregables futuros.
