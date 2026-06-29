# Diseño — Entregable D: Market Setup time-aware (minuto + marcador)

> **Fecha:** 2026-06-29
> **Alcance:** Hacer que la **misma** página Market Setup contemple el minuto y
> el marcador del partido en curso para recalcular las probabilidades y stats de
> forma correcta. La calibración pasa de "90 min desde 0-0" a **λ restantes
> condicionados al marcador actual**, calibrados al precio live. Sin xG, sin
> edge. Datos de minuto/marcador desde el **mismo evento de Polymarket**.

---

## 1. Decisión central y fuente de datos

| Decisión | Elección |
|---|---|
| Página | La misma (Market Setup), no una nueva |
| Qué representan los valores live | **Vista del mercado corregida por el tiempo** (λ restantes calibrados al precio live + marcador). Sin xG, sin edge. |
| Fuente de minuto + marcador | **Polymarket** (mismo evento Gamma). ESPN como fallback. |

**Campos live de Polymarket** (verificados en el evento Gamma, mismo que ya
consultamos): `live` (bool/None), `period` (`1H`/`2H`/`HT`/`VFT`…), `score`
(`"1-1"`), `elapsed` (minuto como string). Cross-validado contra ESPN
`site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard` (gratis,
sin key), que queda como **fallback** si Polymarket no trae los campos.

**Fixtures capturados** (`tests/fixtures/`): `wc_match_main.json` (live 0-0),
`wc_match_live_scored.json` (live 1-1, 2H, min 70), `wc_match_pre.json`
(no empezado), `wc_match_post.json` (terminado, VFT 2-1).

---

## 2. Connector: estado live (`src/connectors/polymarket.py`)

Nueva dataclass y parsing puro:

```python
@dataclass
class LiveState:
    is_live: bool          # de `live` == True
    status: str            # "pre" | "in" | "halftime" | "post"
    minute: float | None   # de `elapsed`
    home_score: int | None # de `score` "1-1" -> 1
    away_score: int | None # -> 1
```

- `parse_live_state(event_json) -> LiveState`. Mapeo de `period`:
  `1H`/`2H`→`"in"`, `HT`→`"halftime"`, `VFT`/`FT`→`"post"`, vacío o `live=None`→`"pre"`.
  `score="H-A"` → ints; `elapsed` → float (None si vacío).
- `MatchMarkets` gana el campo `live: LiveState`.
- Fallback opcional `espn_live_state(home_team, away_team) -> LiveState | None`
  (parsea el scoreboard de ESPN; matchea por nombre de equipo). Se usa solo si
  los campos de Polymarket vienen vacíos para un partido que debería estar en
  juego. **HTTP aislado e inyectable**, como el resto del connector.

---

## 3. Calibración de λ restantes (`src/models/`)

Función nueva (reusa la lógica de marcador-condicionado de `live_update`, pero
**invertida** para calibrar):

```python
def calibrate_remaining(target_probs, home_score, away_score,
                        model="dixon_coles", rho=None, config=...) -> dict
```

- Dado el 1X2 live **normalizado** + marcador `(H, A)`, optimiza
  `(λ_home_rem, λ_away_rem)` tal que el modelo condicionado al marcador (goles
  restantes Poisson/Dixon-Coles, resultado final = `(H+i, A+j)`) reproduzca el
  precio live. 2 incógnitas, 2 restricciones (el 1X2 suma 1) → identificable,
  igual que pre-partido pero partiendo de `(H,A)` en vez de `0-0`.
- `rho` fijo en `default_rho` para live (con solo 1X2 no se identifica un tercer
  parámetro). El selector Poisson/Dixon-Coles se respeta.
- Devuelve `{lambda_home_remaining, lambda_away_remaining, loss, success}`.
- El **minuto** no entra a la calibración (los λ restantes ya representan "lo que
  queda"); se usa solo para mostrar y para el desglose de goles esperados.

Ubicación: extender `calibration.py` (o `live_update.py`); mantener el motor A
intacto. Pre-partido sigue usando `calibrate(...)` actual.

---

## 4. Analítica live (`src/models/analytics.py`)

**Truco central:** construir la **matriz de marcador final** = matriz de goles
*restantes* desplazada por `(H, A)`:

```python
def final_score_matrix(remaining_matrix, home_score, away_score, max_goals) -> np.ndarray
```

`final[H+i, A+j] += remaining[i, j]` (recortando/acumulando en el borde
`max_goals`). Sobre esta matriz final, **la analítica existente se reutiliza sin
cambios** y entrega el número correcto del *resultado final*:

- `one_x_two`, `total_goals_distribution`, `over_under`, `btts`, `clean_sheets`,
  `winning_margin`, `top_scores`, `double_chance` → se aplican a `final_matrix`.
- Quedan correctas por construcción: con 1-1, BTTS=1 (final_home≥1 y final_away≥1);
  Over 0.5 = 1 (total ya ≥2); valla invicta de quien ya recibió = 0.

Lo que necesita lógica nueva:
- **Goles esperados (live)**: desglose `marcados=(H,A)` + `restantes=(λ_rem)` +
  `total_proyectado = H+A+λ_home_rem+λ_away_rem`.
- **Próximo en anotar**: `next_to_score(λ_home_rem, λ_away_rem)` (misma fórmula
  que `first_to_score`). La página lo rotula "primer gol" si va 0-0, o
  "próximo en anotar" si ya hubo goles (el orden real del primer gol no es
  recuperable solo del marcador).

`model_vs_market` en live usa las probs del modelo sobre `final_matrix` contra el
precio live de cada mercado.

---

## 5. UX de la página (`app/pages/01_market_setup.py`)

La página detecta el estado desde `mm.live.status` y se adapta (mismo tab):

- **Pre-partido** (`pre`): comportamiento actual (90 min desde 0-0). Etiqueta
  "Pre-partido". Calibra con `calibrate(...)`.
- **🟢 EN VIVO** (`in`/`halftime`): banner destacado
  `🟢 EN VIVO · min {minuto} · {H}-{A} · {period}`. Calibra con
  `calibrate_remaining(...)`; construye `final_matrix`; toda la analítica se
  computa sobre ella y se rotula **"proyección final"**. Goles muestra
  *marcado vs restante vs total*. El bloque "primer gol" pasa a "próximo en
  anotar". El modelo guardado en sesión sigue siendo compatible con Live Match.
- **Terminado** (`post`): muestra marcador final + nota "Partido terminado"; no
  calibra (los precios ya no son accionables).

El botón **"Actualizar precios"** sigue (trae precio + minuto + marcador
frescos) y el sello de "Última actualización". **Auto-refresco fuera de alcance**
(evita dependencia extra; se puede sumar después).

---

## 6. Testing

- **Connector** (`test_polymarket_connector.py`): `parse_live_state` sobre los 4
  fixtures → `main`/`live_scored` = "in" con minuto/marcador correctos,
  `pre` = "pre" (campos None), `post` = "post" con marcador final. `MatchMarkets`
  incluye `live`.
- **Calibración live** (`test_live_calibration.py` o en `test_calibration.py`):
  round-trip — los λ restantes recuperados, condicionados al marcador,
  reproducen el 1X2 objetivo dentro de tolerancia. Caso 0-0 ≈ comportamiento
  pre-partido.
- **Analítica live** (`test_analytics.py`): `final_score_matrix` desplaza bien
  (P(total final) corrido por `H+A`; Over ya superado → 1; BTTS con ambos
  marcados → 1; valla invicta imposible → 0; `next_to_score` suma 1).
- **Página** (`test_market_setup_page.py`): AppTest con connector mockeado en
  estado **live** (banner + stats live renderizan, modelo guardado) y
  **pre** (comportamiento de hoy), sin red.

---

## 7. Fuera de alcance
xG y edge (Entregable E aparte), auto-refresco automático, orden real del primer
gol, mercados por tiempo (1er/2do tiempo), persistencia SQLite.
