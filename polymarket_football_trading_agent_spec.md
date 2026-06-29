# Especificación para agente: Dashboard y motor de trading live para fútbol en Polymarket

> **Objetivo del proyecto:** construir una herramienta que tome precios de Polymarket como punto de partida, los convierta en un modelo probabilístico de fútbol usando Poisson, y luego actualice esas probabilidades en vivo con minuto, marcador, xG, momentum, tiros, tarjetas y otros eventos del partido. La primera versión debe ser un **dashboard de análisis y paper trading**, no un bot automático de ejecución.

---

## 1. Principio central del sistema

El sistema debe partir desde una idea simple:

> **El mercado de Polymarket entrega una probabilidad implícita inicial. El modelo Poisson traduce esa probabilidad en goles esperados por equipo. Luego, durante el partido, el modelo se actualiza con información live para detectar si el precio del mercado está caro o barato.**

En fútbol, el precio del empate no solo depende del marcador. Depende de:

- minuto actual;
- marcador actual;
- probabilidad pre-partido;
- fortaleza ofensiva relativa;
- goles esperados implícitos por mercado;
- xG acumulado;
- xG reciente;
- tiros de alta calidad;
- presión territorial;
- tarjetas;
- sustituciones;
- liquidez y spread del mercado.

La herramienta no debe entregar una recomendación binaria tipo “apostar / no apostar”. Debe entregar:

- probabilidad de mercado;
- probabilidad estimada por modelo;
- diferencia o edge;
- spread y liquidez;
- riesgo de ejecución;
- escenarios posibles;
- precio objetivo;
- probabilidad de que el trade llegue a ese precio;
- stop-loss sugerido;
- tamaño máximo sugerido según riesgo.

---

## 2. Alcance de la primera versión

### MVP obligatorio

La primera versión debe hacer lo siguiente:

1. Buscar o recibir manualmente un mercado de fútbol de Polymarket.
2. Leer precios de los tres resultados principales:
   - gana equipo A;
   - empate;
   - gana equipo B.
3. Normalizar precios para obtener probabilidades implícitas.
4. Calibrar un modelo Poisson con esos precios.
5. Mostrar:
   - lambdas iniciales;
   - probabilidades 1X2;
   - tabla de marcadores más probables;
   - curva del precio justo del empate si el partido sigue 0-0.
6. Permitir entrada manual de:
   - minuto actual;
   - marcador;
   - xG equipo A;
   - xG equipo B;
   - xG últimos 10 minutos;
   - tarjetas rojas;
   - precio live actual del mercado.
7. Recalcular probabilidades live.
8. Graficar:
   - precio de mercado vs probabilidad del modelo;
   - xG acumulado;
   - xG reciente;
   - probabilidad del empate en el tiempo;
   - edge ajustado por spread.
9. Registrar snapshots para backtesting.
10. Simular trades sin ejecutar dinero real.

### No hacer en MVP

No construir todavía:

- ejecución automática de órdenes;
- apalancamiento;
- estrategia multi-partido;
- optimización agresiva de tamaño;
- arbitraje multi-mercado complejo;
- scraping frágil sin fallback;
- recomendaciones sin mostrar incertidumbre.

---

## 3. Arquitectura recomendada

Usar una arquitectura modular.

```text
polymarket-football-trader/
├── app/
│   ├── dashboard.py
│   ├── pages/
│   │   ├── 01_market_setup.py
│   │   ├── 02_live_match.py
│   │   ├── 03_backtest.py
│   │   └── 04_strategy_lab.py
├── src/
│   ├── connectors/
│   │   ├── polymarket.py
│   │   ├── xg_provider.py
│   │   ├── manual_provider.py
│   │   └── odds_provider.py
│   ├── models/
│   │   ├── poisson.py
│   │   ├── calibration.py
│   │   ├── live_update.py
│   │   └── dixon_coles.py
│   ├── strategy/
│   │   ├── draw_scalp.py
│   │   ├── risk.py
│   │   ├── execution_simulator.py
│   │   └── signals.py
│   ├── storage/
│   │   ├── db.py
│   │   ├── schemas.py
│   │   └── snapshots.py
│   ├── charts/
│   │   ├── probability_charts.py
│   │   ├── xg_charts.py
│   │   └── orderbook_charts.py
│   └── utils/
│       ├── time.py
│       ├── math.py
│       └── validation.py
├── tests/
│   ├── test_poisson.py
│   ├── test_calibration.py
│   ├── test_live_update.py
│   └── test_strategy_draw_scalp.py
├── notebooks/
│   ├── poisson_sandbox.ipynb
│   └── live_trade_simulation.ipynb
├── data/
│   ├── raw/
│   ├── processed/
│   └── backtests/
├── README.md
├── requirements.txt
└── .env.example
```

---

## 4. Fuentes de datos

### 4.1 Polymarket

Usar Polymarket para:

- descubrir eventos y mercados;
- leer precios;
- leer order books;
- leer spreads;
- leer volumen;
- leer liquidez;
- registrar snapshots de precios;
- eventualmente enviar órdenes, pero solo en una etapa posterior.

Polymarket tiene distintas APIs. La estructura a considerar es:

- **Gamma API:** descubrimiento de eventos y metadata de mercados.
- **Data API:** datos públicos de actividad, trades y otros datos históricos.
- **CLOB API:** orderbook, precios y eventualmente manejo de órdenes.

En la primera versión se debe usar Polymarket solo en modo lectura.

### 4.2 Fuente live de xG

La herramienta debe tener una interfaz genérica para proveedores de xG.

No acoplar el modelo a un proveedor específico. Crear esta abstracción:

```python
class XGProvider:
    def get_match_state(self, match_id: str) -> MatchState:
        ...
```

Donde `MatchState` debe devolver:

```python
@dataclass
class MatchState:
    minute: float
    home_score: int
    away_score: int
    home_xg: float | None
    away_xg: float | None
    home_xg_last_10: float | None
    away_xg_last_10: float | None
    home_shots: int | None
    away_shots: int | None
    home_shots_on_target: int | None
    away_shots_on_target: int | None
    home_red_cards: int
    away_red_cards: int
    timestamp_utc: datetime
    source: str
    data_quality: str
```

Debe existir también un `ManualProvider` para ingresar datos manualmente cuando no haya API confiable.

---

## 5. Modelo inicial: Poisson calibrado desde Polymarket

### 5.1 Inputs iniciales

Para un partido con tres outcomes:

```text
P_raw_home = precio mercado de gana equipo local/favorito
P_raw_draw = precio mercado de empate
P_raw_away = precio mercado de gana equipo visitante/underdog
```

Ejemplo:

```text
Argentina gana = 0.86
Empate = 0.11
Cabo Verde gana = 0.04
```

Estos precios pueden sumar más o menos que 1 por spread, fees, falta de liquidez o asincronía.

Normalizar:

```python
total = P_raw_home + P_raw_draw + P_raw_away

P_home = P_raw_home / total
P_draw = P_raw_draw / total
P_away = P_raw_away / total
```

Ejemplo:

```text
total = 0.86 + 0.11 + 0.04 = 1.01

P_home = 0.86 / 1.01 = 0.8515
P_draw = 0.11 / 1.01 = 0.1089
P_away = 0.04 / 1.01 = 0.0396
```

Estas son las probabilidades limpias que debe intentar reproducir el modelo.

---

## 6. Poisson independiente

El supuesto inicial:

```text
Goles equipo A ~ Poisson(lambda_A)
Goles equipo B ~ Poisson(lambda_B)
```

La probabilidad de que un equipo anote `k` goles es:

```text
P(k goles) = exp(-lambda) * lambda^k / k!
```

Para cada marcador posible:

```text
P(marcador A=i, B=j) = P_A(i) * P_B(j)
```

Luego:

```text
P(A gana) = suma de P(i,j) donde i > j
P(empate) = suma de P(i,j) donde i = j
P(B gana) = suma de P(i,j) donde i < j
```

---

## 7. Calibración de lambdas

El agente debe encontrar `lambda_A` y `lambda_B` que mejor reproduzcan las probabilidades del mercado.

### 7.1 Objetivo de optimización

Definir:

```python
target = {
    "home": P_home,
    "draw": P_draw,
    "away": P_away,
}
```

Para un par de lambdas:

```python
model = poisson_1x2(lambda_home, lambda_away)
```

Minimizar:

```python
loss = (
    w_home * (model["home"] - target["home"]) ** 2
    + w_draw * (model["draw"] - target["draw"]) ** 2
    + w_away * (model["away"] - target["away"]) ** 2
)
```

Pesos recomendados:

```python
w_home = 1.0
w_draw = 1.2
w_away = 1.0
```

Se puede dar un poco más de peso al empate porque suele ser el outcome que más importa para estrategias de “draw scalp”.

### 7.2 Bounds recomendados

```python
lambda_home_min = 0.05
lambda_home_max = 6.00

lambda_away_min = 0.05
lambda_away_max = 4.00
```

Si es un partido extremadamente desigual, permitir hasta:

```python
lambda_home_max = 7.50
lambda_away_max = 5.00
```

### 7.3 Pseudocódigo

```python
from scipy.optimize import minimize

def calibrate_lambdas(target_probs):
    def objective(x):
        lambda_home, lambda_away = x
        model_probs = poisson_1x2(lambda_home, lambda_away, max_goals=12)
        return (
            1.0 * (model_probs["home"] - target_probs["home"]) ** 2
            + 1.2 * (model_probs["draw"] - target_probs["draw"]) ** 2
            + 1.0 * (model_probs["away"] - target_probs["away"]) ** 2
        )

    result = minimize(
        objective,
        x0=[1.7, 1.0],
        bounds=[(0.05, 6.0), (0.05, 4.0)],
        method="L-BFGS-B",
    )

    return {
        "lambda_home": result.x[0],
        "lambda_away": result.x[1],
        "loss": result.fun,
        "success": result.success,
    }
```

### 7.4 Validaciones

Después de calibrar:

```python
assert 0.99 <= sum(model_probs.values()) <= 1.01
assert lambda_home > 0
assert lambda_away > 0
```

Además, el sistema debe levantar una advertencia si:

```text
abs(model_home - market_home) > 0.03
abs(model_draw - market_draw) > 0.03
abs(model_away - market_away) > 0.03
```

Esto significa que el Poisson simple no está reproduciendo bien el mercado y se debe usar información adicional, como over/under, exact score o un modelo Dixon-Coles.

---

## 8. Incluir mercados adicionales cuando estén disponibles

Si Polymarket también ofrece:

- Over/Under 2.5;
- spread;
- exact score;
- halves;
- team totals;

usar esos mercados para mejorar la calibración.

### 8.1 Over/Under 2.5

Si se tiene precio de Over 2.5:

```text
P_over_2_5_market
```

Agregar a la pérdida:

```python
loss += w_over * (model_over_2_5 - P_over_2_5_market) ** 2
```

Donde:

```python
model_over_2_5 = P(total_goals >= 3)
```

Peso recomendado:

```python
w_over = 0.8
```

El total de goles es muy útil porque ayuda a separar dos partidos con el mismo 1X2 pero ritmos distintos.

---

## 9. Modelo live por minuto y marcador

### 9.1 Remaining lambdas base

Si el partido va en el minuto `t`, quedan:

```python
remaining_fraction = max(0, 90 - t) / 90
```

Entonces:

```python
lambda_home_remaining_base = lambda_home_initial * remaining_fraction
lambda_away_remaining_base = lambda_away_initial * remaining_fraction
```

Para un partido 0-0 al minuto 45:

```text
lambda_home_initial = 2.76
lambda_away_initial = 0.46

lambda_home_remaining_base = 2.76 * 45/90 = 1.38
lambda_away_remaining_base = 0.46 * 45/90 = 0.23
```

### 9.2 Probabilidades condicionadas al marcador actual

Si el partido va:

```text
home_score = H
away_score = A
```

Entonces modelar goles restantes:

```text
Goles restantes home ~ Poisson(lambda_home_remaining)
Goles restantes away ~ Poisson(lambda_away_remaining)
```

Resultado final:

```text
home_final = H + goles_restantes_home
away_final = A + goles_restantes_away
```

Luego calcular:

```python
P_home_win_live = P(home_final > away_final)
P_draw_live = P(home_final == away_final)
P_away_win_live = P(home_final < away_final)
```

Esto permite modelar escenarios como:

- 0-0 minuto 30;
- 1-0 minuto 30;
- 0-1 minuto 30;
- 1-1 minuto 70;
- etc.

---

## 10. Actualización live con xG

### 10.1 Idea

No todos los 0-0 son iguales.

Un 0-0 con Argentina generando 2.0 xG al descanso es muy distinto a un 0-0 con Argentina generando solo 0.25 xG.

Por eso, el modelo debe ajustar los lambdas restantes usando xG.

### 10.2 Variables

```python
minute = minuto actual
home_xg = xG acumulado del equipo A
away_xg = xG acumulado del equipo B
home_xg_last_10 = xG últimos 10 minutos del equipo A
away_xg_last_10 = xG últimos 10 minutos del equipo B
```

### 10.3 Estimar ritmo live

Ritmo full-match implícito desde xG acumulado:

```python
home_xg_pace_full = home_xg * 90 / max(minute, 1)
away_xg_pace_full = away_xg * 90 / max(minute, 1)
```

Ejemplo:

```text
minuto = 30
Argentina xG = 0.20

xG pace full = 0.20 * 90 / 30 = 0.60
```

Esto significa que, si el partido siguiera al mismo ritmo, Argentina terminaría con 0.60 xG, muy por debajo del prior inicial.

### 10.4 Shrinkage contra prior

No confiar demasiado en pocos minutos de datos. Usar una mezcla entre prior de mercado y ritmo live.

```python
tau = 25
w_live = minute / (minute + tau)

lambda_home_full_adjusted = (
    (1 - w_live) * lambda_home_initial
    + w_live * home_xg_pace_full
)

lambda_away_full_adjusted = (
    (1 - w_live) * lambda_away_initial
    + w_live * away_xg_pace_full
)
```

Interpretación:

- al minuto 5, manda más el prior;
- al minuto 45, el xG live pesa más;
- al minuto 70, el partido observado pesa mucho más que el prior.

### 10.5 Ajuste por xG reciente

El xG acumulado puede ocultar cambios recientes. Agregar momentum:

```python
window = 10

home_recent_pace_full = home_xg_last_10 * 90 / window
away_recent_pace_full = away_xg_last_10 * 90 / window
```

Luego:

```python
recent_weight = 0.25

lambda_home_full_adjusted = (
    (1 - recent_weight) * lambda_home_full_adjusted
    + recent_weight * home_recent_pace_full
)

lambda_away_full_adjusted = (
    (1 - recent_weight) * lambda_away_full_adjusted
    + recent_weight * away_recent_pace_full
)
```

### 10.6 Convertir a lambdas restantes

```python
remaining_fraction = max(0, 90 - minute) / 90

lambda_home_remaining = lambda_home_full_adjusted * remaining_fraction
lambda_away_remaining = lambda_away_full_adjusted * remaining_fraction
```

### 10.7 Caps de seguridad

Para evitar que el modelo explote por datos ruidosos:

```python
lambda_home_remaining = clip(
    lambda_home_remaining,
    0.20 * lambda_home_remaining_base,
    2.50 * lambda_home_remaining_base,
)

lambda_away_remaining = clip(
    lambda_away_remaining,
    0.20 * lambda_away_remaining_base,
    2.50 * lambda_away_remaining_base,
)
```

Si hay tarjeta roja, permitir multiplicadores mayores.

---

## 11. Ajustes por eventos del partido

### 11.1 Tarjeta roja

Si equipo A recibe roja:

```python
lambda_A_remaining *= 0.60
lambda_B_remaining *= 1.25
```

Si equipo B recibe roja:

```python
lambda_A_remaining *= 1.25
lambda_B_remaining *= 0.60
```

Estos multiplicadores deben ser configurables y calibrados con backtesting.

### 11.2 Lesión o sustitución importante

Inicialmente manejar manualmente:

```python
home_attack_multiplier = 1.00
away_attack_multiplier = 1.00
```

Ejemplos:

```text
Favorito mete delantero ofensivo: lambda_favorito *= 1.08
Favorito saca jugador creativo: lambda_favorito *= 0.92
Underdog se queda sin central: lambda_favorito *= 1.12
```

### 11.3 Cambio táctico

Agregar controles manuales:

```text
tempo_multiplier_home
tempo_multiplier_away
defensive_block_multiplier
```

No automatizar esta parte en MVP.

---

## 12. Estrategia específica: comprar empate para vender más arriba

### 12.1 Descripción

La estrategia que se quiere modelar:

> Comprar shares de empate cuando el precio está bajo, esperando que el partido siga 0-0 y el precio del empate suba con el paso del tiempo. Luego vender antes del final, sin necesariamente esperar que el partido termine empatado.

Esto es un trade de tiempo y marcador, no una apuesta pura al resultado final.

### 12.2 Variables principales

```python
entry_price = precio de compra del empate
target_price = precio objetivo de venta
stop_price = precio de salida si el favorito marca
current_minute = minuto actual
target_minute = minuto estimado donde el empate alcanza target_price
shares = capital / entry_price
```

### 12.3 Curva de precio justo si sigue 0-0

Para cada minuto futuro `m`, si el marcador sigue 0-0:

```python
remaining_fraction = (90 - m) / 90
lambda_home_rem = lambda_home_initial * remaining_fraction
lambda_away_rem = lambda_away_initial * remaining_fraction

fair_draw_price[m] = P(final_draw | score=0-0, minute=m)
```

Esto genera una curva:

```text
min 0  -> empate vale aprox. precio inicial
min 30 -> empate sube
min 45 -> empate sube más
min 60 -> puede acercarse a 0.40 si el favorito era muy fuerte
min 75 -> sube agresivamente si sigue 0-0
```

### 12.4 Probabilidad de llegar al target sin goles

Si el target se alcanza al minuto `target_minute`, calcular:

```python
delta_t = target_minute - current_minute
goal_intensity_per_min = (
    lambda_home_remaining + lambda_away_remaining
) / max(90 - current_minute, 1)

prob_no_goal_until_target = exp(-goal_intensity_per_min * delta_t)
```

Esto estima la probabilidad de que el partido siga sin goles hasta el objetivo.

### 12.5 EV simplificada del trade

```python
profit_if_target = target_price - entry_price
loss_if_stop = entry_price - stop_price

EV_per_share = (
    prob_no_goal_until_target * profit_if_target
    - (1 - prob_no_goal_until_target) * loss_if_stop
)
```

Ajustar por spread:

```python
EV_per_share_adjusted = EV_per_share - estimated_spread_cost - slippage_buffer
```

No entrar si:

```python
EV_per_share_adjusted <= 0
```

### 12.6 Reglas de gestión

Para un trade de empate:

```text
Entrada:
- Solo si spread bajo.
- Solo si hay liquidez suficiente.
- Solo si el modelo no muestra que el favorito está generando peligro excesivo.
- Evitar entrar si el favorito ya tiene xG alto muy temprano.

Take profit:
- Vender 30%-50% cuando el precio suba 70%-120% desde entrada.
- Vender otra parte al descanso si el partido sigue frío.
- Dejar solo una parte pequeña para el escenario de 0-0 avanzado.

Stop:
- Si favorito marca, salir rápido o aceptar pérdida.
- Si xG del favorito se dispara, reducir exposición aunque el marcador siga 0-0.
- Si el spread se abre demasiado, evitar quedar atrapado.

No promediar abajo:
- Si el favorito marca, no comprar más empate solo porque está barato.
```

---

## 13. Señales del modelo

Crear estas señales:

### 13.1 Edge bruto

```python
edge = model_probability - market_mid_probability
```

Ejemplo:

```text
modelo cree empate = 0.18
mercado empate = 0.14

edge = +0.04
```

### 13.2 Edge ejecutable

Para comprar:

```python
executable_edge_buy = model_probability - best_ask
```

Para vender:

```python
executable_edge_sell = best_bid - model_probability
```

Usar siempre best bid / best ask. No usar solo last price.

### 13.3 Señal de scalp de empate

```python
draw_scalp_signal = (
    score_home == score_away
    and current_minute <= 65
    and executable_edge_buy > min_edge
    and favorite_xg_risk < threshold
    and spread < max_spread
    and liquidity > min_liquidity
)
```

### 13.4 Riesgo por xG

```python
favorite_xg_expected_by_now = lambda_favorite_initial * current_minute / 90

favorite_xg_ratio = favorite_xg_actual / max(favorite_xg_expected_by_now, 0.01)
```

Interpretación:

```text
ratio < 0.60  -> favorito está generando poco
ratio 0.60-1.20 -> normal
ratio > 1.20 -> favorito está generando más de lo esperado
ratio > 1.80 -> peligro alto
```

---

## 14. Dashboard

### 14.1 Pantalla 1: Setup del mercado

Campos:

- nombre del partido;
- URL o ID de mercado de Polymarket;
- equipo A;
- equipo B;
- precio A;
- precio empate;
- precio B;
- best bid / best ask;
- volumen;
- liquidez;
- hora de inicio.

Output:

- probabilidades normalizadas;
- lambdas calibrados;
- pérdida de calibración;
- advertencias de liquidez;
- tabla de marcadores probables.

### 14.2 Pantalla 2: Live match

Inputs manuales o API:

- minuto;
- marcador;
- xG A;
- xG B;
- xG últimos 10 minutos A/B;
- tiros;
- tiros al arco;
- tarjetas rojas;
- precio actual de empate;
- best bid/ask.

Outputs:

- probabilidad live de A/empate/B;
- precio justo del empate;
- edge;
- EV estimada;
- probabilidad de llegar al target;
- recomendación textual del modelo:
  - “no trade”;
  - “watch”;
  - “small position”;
  - “take partial profit”;
  - “reduce risk”;
  - “exit”.

### 14.3 Pantalla 3: Gráficos obligatorios

Crear gráficos separados:

1. **Probabilidad del empate**
   - mercado;
   - modelo base;
   - modelo ajustado con xG.

2. **xG acumulado**
   - equipo A;
   - equipo B.

3. **xG últimos 10 minutos**
   - equipo A;
   - equipo B.

4. **Precio justo si sigue 0-0**
   - curva desde minuto actual hasta 90.

5. **Edge ejecutable**
   - modelo menos ask para compra;
   - bid menos modelo para venta.

6. **Order book**
   - bid/ask;
   - spread;
   - profundidad.

### 14.4 Pantalla 4: Paper trading

Registrar:

- hora de entrada;
- minuto de entrada;
- precio de entrada;
- cantidad de shares;
- tesis;
- xG al entrar;
- precio objetivo;
- stop;
- hora de salida;
- precio de salida;
- P&L;
- si la señal era válida según reglas.

---

## 15. Storage

Usar SQLite para MVP. Luego migrar a Postgres.

### 15.1 Tabla `market_snapshots`

```sql
CREATE TABLE market_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp_utc TEXT NOT NULL,
    match_id TEXT NOT NULL,
    market_id TEXT NOT NULL,
    outcome TEXT NOT NULL,
    best_bid REAL,
    best_ask REAL,
    mid_price REAL,
    last_price REAL,
    spread REAL,
    liquidity REAL,
    volume REAL
);
```

### 15.2 Tabla `match_snapshots`

```sql
CREATE TABLE match_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp_utc TEXT NOT NULL,
    match_id TEXT NOT NULL,
    minute REAL NOT NULL,
    home_score INTEGER NOT NULL,
    away_score INTEGER NOT NULL,
    home_xg REAL,
    away_xg REAL,
    home_xg_last_10 REAL,
    away_xg_last_10 REAL,
    home_shots INTEGER,
    away_shots INTEGER,
    home_red_cards INTEGER,
    away_red_cards INTEGER,
    source TEXT,
    data_quality TEXT
);
```

### 15.3 Tabla `model_snapshots`

```sql
CREATE TABLE model_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp_utc TEXT NOT NULL,
    match_id TEXT NOT NULL,
    minute REAL NOT NULL,
    home_score INTEGER NOT NULL,
    away_score INTEGER NOT NULL,
    lambda_home_initial REAL NOT NULL,
    lambda_away_initial REAL NOT NULL,
    lambda_home_remaining_base REAL NOT NULL,
    lambda_away_remaining_base REAL NOT NULL,
    lambda_home_remaining_adjusted REAL NOT NULL,
    lambda_away_remaining_adjusted REAL NOT NULL,
    model_home_prob REAL NOT NULL,
    model_draw_prob REAL NOT NULL,
    model_away_prob REAL NOT NULL,
    market_home_prob REAL,
    market_draw_prob REAL,
    market_away_prob REAL,
    draw_edge REAL,
    calibration_loss REAL
);
```

### 15.4 Tabla `paper_trades`

```sql
CREATE TABLE paper_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id TEXT NOT NULL,
    strategy TEXT NOT NULL,
    side TEXT NOT NULL,
    outcome TEXT NOT NULL,
    entry_timestamp_utc TEXT NOT NULL,
    entry_minute REAL NOT NULL,
    entry_price REAL NOT NULL,
    shares REAL NOT NULL,
    target_price REAL,
    stop_price REAL,
    thesis TEXT,
    exit_timestamp_utc TEXT,
    exit_minute REAL,
    exit_price REAL,
    pnl REAL,
    status TEXT NOT NULL
);
```

---

## 16. Backtesting

### 16.1 Objetivo

Validar si las señales realmente habrían ganado dinero.

No basta con que el modelo “prediga bien”. Debe ganar después de:

- spread;
- slippage;
- baja liquidez;
- delay del dato;
- imposibilidad de vender al precio teórico;
- volatilidad del mercado;
- goles repentinos.

### 16.2 Métricas de backtest

Medir:

- ROI;
- P&L total;
- win rate;
- profit factor;
- max drawdown;
- Sharpe simplificado;
- peor pérdida;
- mejor trade;
- duración promedio del trade;
- edge promedio al entrar;
- edge realizado;
- cuánto se perdió por spread;
- cuánto se perdió por delay.

### 16.3 Backtest realista

No usar precio medio como si fuera ejecutable.

Para comprar:

```text
entrada = best_ask
```

Para vender:

```text
salida = best_bid
```

Si no hay suficiente liquidez en el nivel 1, simular slippage.

---

## 17. Risk management

### 17.1 Tamaño de posición

No arriesgar más de un porcentaje pequeño del bankroll por trade.

Parámetros iniciales:

```python
max_bankroll_risk_per_trade = 0.01  # 1%
max_position_size = 0.03            # 3% bankroll
```

### 17.2 Kelly fraccional

Si se calcula edge real, usar Kelly fraccional muy conservador.

Para una apuesta binaria pura:

```python
kelly_fraction = (p * b - q) / b
```

Donde:

```text
p = probabilidad modelo
q = 1 - p
b = payout neto / costo
```

Pero para scalping live esto es más complejo porque el trade se cierra antes del resultado. En MVP usar Kelly solo como referencia y limitar con caps duros.

### 17.3 Reglas duras

```text
No entrar si spread > 6 puntos porcentuales.
No entrar si liquidez disponible < tamaño objetivo * 3.
No entrar si el dato live tiene más de 60 segundos de atraso.
No entrar si el modelo no pudo calibrar correctamente.
No entrar si el mercado está suspendido o con pricing errático.
No aumentar posición después de un gol en contra.
No usar martingala.
```

---

## 18. Interpretación de señales para empate

### 18.1 Buen escenario para comprar empate

```text
Marcador: 0-0
Minuto: 15-40
Precio de empate aún bajo
Favorito con xG bajo o normal
Underdog defendiendo bien
Pocos tiros claros
Spread bajo
Buena liquidez
Modelo > mercado por al menos 3-5 puntos porcentuales
```

### 18.2 Mal escenario aunque siga 0-0

```text
Favorito con xG alto
Muchos tiros dentro del área
Arquero del underdog salvando varias
Corners consecutivos
Defensores con amarilla
Underdog no sale de su área
Precio de empate subió pero el riesgo real también
Spread amplio
Liquidez pobre
```

### 18.3 Take profit parcial

Ejemplo:

```text
Entrada: 0.11
TP1: 0.20-0.23 -> vender 30%-50%
TP2: 0.28-0.32 -> vender otra parte
TP3: 0.38-0.42 -> vender casi todo
Runner: dejar 5%-10% si el partido está realmente frío
```

---

## 19. Calidad de datos y alertas

Cada snapshot debe tener un estado:

```text
OK
STALE
MISSING_XG
LOW_LIQUIDITY
HIGH_SPREAD
MARKET_SUSPENDED
API_ERROR
MANUAL_MODE
```

No entregar señales fuertes si el estado no es `OK`.

### 19.1 Latencia

Guardar:

```python
data_timestamp_utc
received_timestamp_utc
latency_seconds
```

Si:

```python
latency_seconds > 60
```

marcar como `STALE`.

---

## 20. Tests mínimos

### 20.1 Tests de Poisson

- Las probabilidades de marcadores deben sumar cerca de 1.
- `P_home + P_draw + P_away` debe sumar 1.
- Si `lambda_home > lambda_away`, `P_home` debe ser mayor que `P_away`.
- Si lambdas iguales, probabilidades home y away deben ser similares.

### 20.2 Tests de curva 0-0

Si el partido sigue 0-0:

- probabilidad de empate debe subir con el tiempo;
- probabilidad de que el favorito gane debe bajar;
- probabilidad de 0-0 final debe subir.

### 20.3 Tests de live update

- Al minuto 0, modelo live debe parecerse al pre-partido.
- Al minuto 90, si el marcador está empatado, `P_draw` debe acercarse a 1.
- Al minuto 90, si equipo A gana, `P_home` debe acercarse a 1.
- Si xG favorito es muy alto, lambda restante del favorito debe subir.
- Si xG favorito es muy bajo, lambda restante del favorito debe bajar.

### 20.4 Tests de estrategia

- No generar señal si spread es alto.
- No generar señal si la liquidez es baja.
- No generar señal si xG favorito está excesivamente alto.
- Generar `watch` si el partido está 0-0 pero edge es pequeño.
- Generar `small_position` si edge es positivo, xG bajo y spread razonable.

---

## 21. Roadmap

### Fase 1: Notebook matemático

Construir:

- función Poisson;
- calibración de lambdas;
- curvas live;
- simulación de estrategia de empate.

Output:

- notebook con ejemplo Argentina vs Cabo Verde;
- gráficos;
- explicación de resultados.

### Fase 2: Dashboard manual

Construir Streamlit:

- inputs manuales;
- gráficos;
- cálculo live;
- paper trading.

### Fase 3: Conexión Polymarket

Agregar:

- lectura de mercado;
- precios;
- best bid/ask;
- snapshots;
- orderbook básico.

### Fase 4: xG live

Agregar:

- `XGProvider`;
- proveedor real;
- fallback manual;
- validación de latencia;
- gráficos live.

### Fase 5: Backtesting

Agregar:

- replay de snapshots;
- simulación realista con bid/ask;
- métricas de estrategia.

### Fase 6: Alertas

Agregar:

- alertas por edge;
- alertas por target;
- alertas por stop;
- alertas por cambio de xG;
- alertas por spread/liquidez.

### Fase 7: Ejecución real, solo si todo lo anterior funciona

Antes de ejecutar dinero real:

- backtest positivo;
- paper trading positivo;
- control de riesgo;
- logs completos;
- límites de tamaño;
- kill switch;
- revisión legal/regulatoria.

---

## 22. Configuración sugerida

Archivo `config.yaml`:

```yaml
model:
  max_goals: 12
  draw_weight: 1.2
  tau_minutes: 25
  recent_xg_weight: 0.25
  lambda_cap_min_multiplier: 0.20
  lambda_cap_max_multiplier: 2.50

strategy:
  min_edge: 0.035
  max_spread: 0.06
  min_liquidity_multiplier: 3.0
  max_minute_entry: 65
  partial_take_profit_1: 0.20
  partial_take_profit_2: 0.30
  partial_take_profit_3: 0.40
  stop_after_favorite_goal: true
  no_martingale: true

risk:
  bankroll: 1000
  max_bankroll_risk_per_trade: 0.01
  max_position_size: 0.03
  slippage_buffer: 0.015

data:
  max_data_latency_seconds: 60
  snapshot_interval_seconds: 10
  manual_mode_allowed: true
```

---

## 23. Definición de “listo” para MVP

El MVP está listo cuando el usuario puede:

1. Abrir el dashboard.
2. Ingresar precios iniciales de Polymarket.
3. Ver lambdas calibrados.
4. Ver probabilidades de 1X2.
5. Ver marcadores más probables.
6. Ingresar minuto, marcador y xG live.
7. Ver probabilidad actualizada de empate.
8. Ver si el empate está caro o barato versus mercado.
9. Ver una curva de posible precio si el partido sigue 0-0.
10. Simular un trade de empate.
11. Guardar snapshots.
12. Revisar P&L de paper trading.

---

## 24. Ejemplo conceptual: Argentina vs Cabo Verde

Input inicial:

```text
Argentina = 0.86
Empate = 0.11
Cabo Verde = 0.04
```

Normalización:

```text
Argentina = 0.8515
Empate = 0.1089
Cabo Verde = 0.0396
```

Posible calibración:

```text
lambda_Argentina ≈ 2.76
lambda_CaboVerde ≈ 0.46
```

Interpretación:

```text
El mercado está diciendo, de forma implícita, que Argentina debería generar muchos más goles que Cabo Verde.
```

Si sigue 0-0, el empate sube porque quedan menos minutos para que se materialice la ventaja ofensiva de Argentina.

Pero si al minuto 30 Argentina ya tiene xG 1.3 o más, el 0-0 puede ser engañoso: el precio del empate puede subir, pero el riesgo de gol también es alto.

---

## 25. Instrucción final para el agente desarrollador

Construir el proyecto en este orden:

1. Primero crear el módulo matemático puro de Poisson.
2. Luego crear calibración desde precios Polymarket.
3. Luego crear función live por minuto y marcador.
4. Luego agregar ajuste por xG.
5. Luego crear dashboard manual.
6. Luego crear storage de snapshots.
7. Luego agregar paper trading.
8. Luego conectar Polymarket en modo lectura.
9. Luego conectar proveedor de xG.
10. Solo después evaluar alertas o ejecución real.

No saltarse la fase de paper trading.

El sistema debe priorizar claridad, trazabilidad y control de riesgo sobre velocidad de ejecución.

---

## 26. Referencias técnicas iniciales

- Polymarket Documentation: https://docs.polymarket.com/
- Polymarket API Reference: https://docs.polymarket.com/api-reference/introduction
- Polymarket Market Data Overview: https://docs.polymarket.com/market-data/overview
- Polymarket Gamma API Docs: https://gamma-api.polymarket.com/docs
- Polymarket agent-skills market data notes: https://github.com/Polymarket/agent-skills/blob/main/market-data.md

---

## 27. Nota de riesgo

Este proyecto debe tratarse como herramienta de análisis probabilístico. No garantiza ganancias. Los mercados pueden moverse más rápido que los datos disponibles. Un modelo con edge teórico puede perder dinero por spread, slippage, liquidez, delay, error de datos o eventos repentinos como goles, tarjetas y lesiones.

La primera versión debe ser siempre de análisis y simulación.
