# Diseño — Entregable A: Motor de probabilidades de fútbol

> **Fecha:** 2026-06-29
> **Alcance:** Primer entregable del proyecto Polymarket Football Trading Agent.
> Núcleo matemático puro: convierte precios 1X2 de Polymarket en un modelo
> probabilístico de fútbol (Poisson / Dixon-Coles), lo calibra, y lo actualiza
> en vivo por minuto, marcador y xG. **Sin UI, sin APIs externas, sin estrategia
> de trading.**

---

## 1. Contexto y decisiones tomadas

Este entregable corresponde a la **Fase 1** del spec maestro
(`polymarket_football_trading_agent_spec.md`, sección 25): "primero crear el
módulo matemático puro de Poisson".

Decisiones acordadas en el brainstorming:

| # | Decisión | Elección |
|---|----------|----------|
| 1 | Alcance del primer entregable | **Solo núcleo matemático** (sin dashboard ni Polymarket) |
| 2 | Modelo de goles | **Poisson independiente + Dixon-Coles**, intercambiables y comparables |
| 3 | Calibración de `rho` (Dixon-Coles) | **Fijo ≈ −0.13 por defecto**; se libera y calibra **solo si hay mercado Over/Under** |
| 4 | Forma de verificar | **Notebook Jupyter** con ejemplo Argentina vs Cabo Verde |
| 5 | ¿Incluye matemática de estrategia? | **No.** Solo motor de probabilidades + curva del empate. EV/señales quedan fuera. |

---

## 2. Alcance

### Dentro (este entregable)

- Modelo de marcadores y 1X2 con Poisson independiente.
- Modelo Dixon-Coles (corrección `rho` de marcadores bajos).
- Calibración de lambdas desde precios 1X2 (+ `rho` opcional con Over/Under 2.5).
- Motor live: lambdas restantes por minuto/marcador, ajuste por xG (shrinkage +
  momentum), caps de seguridad, multiplicadores por evento (roja).
- Probabilidades 1X2 condicionadas al marcador actual.
- Curva de precio justo del empate si el partido sigue 0-0.
- Validaciones y advertencias de calibración.
- Notebook de demostración (Argentina vs Cabo Verde).
- Tests unitarios (pytest).

### Fuera (entregables posteriores)

Dashboard Streamlit, conexión a Polymarket, `XGProvider` real, matemática de
estrategia (EV del trade, señales, edge ejecutable, stops), storage SQLite,
paper trading, backtesting, alertas, ejecución real.

---

## 3. Estructura del proyecto

Solo la rebanada necesaria para este entregable (no se crea el árbol completo
del spec maestro todavía):

```text
polymarket-futbol-app/
├── src/
│   ├── models/
│   │   ├── __init__.py
│   │   ├── poisson.py        # matriz de marcadores + 1X2 (Poisson independiente)
│   │   ├── dixon_coles.py    # corrección rho sobre la matriz Poisson
│   │   ├── calibration.py    # ajustar lambdas (+ rho si hay Over/Under)
│   │   └── live_update.py    # lambdas restantes, ajuste xG, eventos, curva del empate
│   └── utils/
│       ├── __init__.py
│       └── validation.py     # checks de sumas=1, lambdas>0, advertencias de calibración
├── notebooks/
│   └── poisson_sandbox.ipynb
├── tests/
│   ├── test_poisson.py
│   ├── test_calibration.py
│   └── test_live_update.py
├── config.yaml               # bloque `model:` del spec maestro
├── requirements.txt
└── .gitignore
```

**Dependencias:** `numpy`, `scipy`, `matplotlib`, `PyYAML`, `pytest`, `jupyter`.
Todas estándar, ampliamente mantenidas.

---

## 4. Componentes

### 4.1 `poisson.py` — modelo base

Responsabilidad: dadas tasas de goles, producir la distribución de marcadores y
las probabilidades 1X2.

Funciones principales:

- `score_matrix(lambda_home, lambda_away, max_goals=12) -> np.ndarray`
  Matriz `(max_goals+1) x (max_goals+1)` con `P(i,j) = pmf(i; λ_h) · pmf(j; λ_a)`.
- `outcome_probs(matrix) -> dict` con `{"home", "draw", "away"}` (suma triángulo
  superior / diagonal / triángulo inferior).
- `top_scores(matrix, n=10) -> list[tuple]` marcadores más probables.
- `prob_total_goals_at_least(matrix, k) -> float` para Over/Under.

### 4.2 `dixon_coles.py` — corrección de marcadores bajos

Responsabilidad: mismo contrato que `poisson.py`, pero aplica el factor de
ajuste `τ(i, j; rho)` de Dixon-Coles a los cuatro marcadores bajos
(0-0, 1-0, 0-1, 1-1) y re-normaliza la matriz.

- `score_matrix(lambda_home, lambda_away, rho, max_goals=12) -> np.ndarray`
- Reusa `outcome_probs`, `top_scores`, etc. de `poisson.py`.

Ambos modelos exponen la **misma interfaz**, seleccionable vía
`model="poisson" | "dixon_coles"`.

### 4.3 `calibration.py` — ajustar el modelo al mercado

Responsabilidad: encontrar los parámetros que reproducen los precios de mercado.

- `normalize_prices(p_home, p_draw, p_away) -> dict` divide por la suma para
  obtener probabilidades implícitas limpias (suman 1).
- `calibrate(target_probs, model="poisson", over_2_5_price=None) -> dict`:
  - Minimiza la pérdida ponderada del spec (pesos `home=1.0`, `draw=1.2`,
    `away=1.0`) con `scipy.optimize.minimize` (L-BFGS-B, bounds del spec
    sección 7.2).
  - **Poisson:** calibra `(λ_home, λ_away)`.
  - **Dixon-Coles sin Over/Under:** `rho` fijo en valor por defecto (≈ −0.13,
    en `config.yaml`); calibra solo los dos lambdas.
  - **Dixon-Coles con Over/Under:** agrega el término
    `w_over · (model_over_2_5 − P_over_2_5_market)²` a la pérdida y libera
    `rho` como tercer parámetro.
  - Devuelve `{lambda_home, lambda_away, rho, loss, success, warnings}`.

### 4.4 `live_update.py` — motor en vivo

Responsabilidad: dado el modelo pre-partido y el estado actual del partido,
recalcular probabilidades live y la curva del empate.

`MatchState` (dataclass, según spec sección 4.2; los campos no usados aún se
mantienen opcionales para compatibilidad futura):

```python
@dataclass
class MatchState:
    minute: float
    home_score: int
    away_score: int
    home_xg: float | None = None
    away_xg: float | None = None
    home_xg_last_10: float | None = None
    away_xg_last_10: float | None = None
    home_red_cards: int = 0
    away_red_cards: int = 0
```

Pipeline (spec secciones 9–11):

1. `remaining_fraction = max(0, 90 - minute) / 90` → `lambda_*_remaining_base`.
2. **Ajuste xG** (si hay datos): ritmo full implícito desde xG acumulado +
   *shrinkage* contra el prior con `w_live = minute / (minute + tau)` (tau=25) +
   momentum de últimos 10 min (peso 0.25). Si no hay xG, se usa solo el base.
3. **Caps de seguridad:** `clip` entre `0.20×` y `2.50×` del base.
4. **Eventos:** multiplicadores por roja (0.60 al equipo afectado, 1.25 al rival),
   configurables.
5. **Probabilidades condicionadas al marcador:** modela goles *restantes* con
   los lambdas ajustados, suma al marcador actual `(H, A)`, y deriva
   `P_home_live / P_draw_live / P_away_live`.

Funciones:

- `adjusted_remaining_lambdas(lambda_home_init, lambda_away_init, state, config) -> dict`
- `live_outcome_probs(lambda_home_init, lambda_away_init, state, config, model, rho) -> dict`
- `fair_draw_curve(lambda_home_init, lambda_away_init, config, model, rho, minutes=range(0, 91, 5)) -> list`
  Precio justo del empate asumiendo marcador 0-0, para cada minuto.

### 4.5 `validation.py` — chequeos y alertas

- Verifica `0.99 ≤ suma(probs) ≤ 1.01` y `lambdas > 0`.
- Genera advertencia si `abs(model_outcome − market_outcome) > 0.03` en cualquier
  outcome (señal de que Poisson simple no reproduce el mercado).

---

## 5. Flujo de datos

```text
Pre-partido:
  precios crudos (1X2 [+ Over/Under])
    → normalize_prices  → target_probs
    → calibrate(model)  → lambdas (+ rho), loss, warnings
    → score_matrix      → outcome_probs, top_scores

Live:
  lambdas_iniciales + MatchState(minuto, marcador, xG, rojas)
    → adjusted_remaining_lambdas
    → live_outcome_probs   → P_home/draw/away live
    → fair_draw_curve      → curva del empate 0-0 (min 0 → 90)
```

---

## 6. Configuración (`config.yaml`)

Bloque `model:` del spec maestro (sección 22), más el `rho` por defecto:

```yaml
model:
  max_goals: 12
  draw_weight: 1.2
  over_weight: 0.8
  tau_minutes: 25
  recent_xg_weight: 0.25
  recent_xg_window: 10
  lambda_cap_min_multiplier: 0.20
  lambda_cap_max_multiplier: 2.50
  default_rho: -0.13
  red_card_attack_multiplier: 0.60
  red_card_opponent_multiplier: 1.25
  lambda_home_bounds: [0.05, 6.0]
  lambda_away_bounds: [0.05, 4.0]
```

---

## 7. Validación

### 7.1 Notebook (`poisson_sandbox.ipynb`)

Ejemplo Argentina vs Cabo Verde de punta a punta:

1. Precios iniciales (0.86 / 0.11 / 0.04) → normalización.
2. Calibración: **Poisson vs Dixon-Coles lado a lado**, comparando cuánto se
   acerca cada uno al empate del mercado.
3. Tabla de marcadores más probables.
4. Escenario live: minuto 30 con **xG bajo (0.2)** vs **xG alto (1.3)**, mostrando
   cómo cambian las probabilidades y los lambdas restantes.
5. Gráfico de la **curva del empate** si sigue 0-0, de minuto 0 a 90.

### 7.2 Tests (pytest) — spec sección 20

- **Poisson:** probabilidades de marcadores ≈ 1; `P_home+P_draw+P_away = 1`;
  `λ_home > λ_away ⇒ P_home > P_away`; lambdas iguales ⇒ `P_home ≈ P_away`.
- **Curva 0-0:** P(empate) sube con el tiempo; P(favorito gana) baja; P(0-0 final)
  sube.
- **Live update:** min 0 ≈ pre-partido; min 90 con marcador empatado ⇒ `P_draw ≈ 1`;
  min 90 con equipo A arriba ⇒ `P_home ≈ 1`; xG favorito alto ⇒ lambda restante
  del favorito sube; xG favorito bajo ⇒ baja.
- **Calibración:** `calibrate` reproduce el mercado dentro de tolerancia para el
  ejemplo; advertencia se dispara cuando corresponde.

---

## 8. Fuera de alcance explícito

Dashboard, Polymarket, `XGProvider` real, estrategia/EV/señales, storage, paper
trading, backtesting, alertas, ejecución real. Cada uno será su propio
entregable con su ciclo spec → plan → implementación.
