# Diseño — Entregable B: Dashboard manual (Streamlit)

> **Fecha:** 2026-06-29
> **Alcance:** Envolver el motor de probabilidades (Entregable A) en una UI
> manual multipágina. El usuario ingresa precios y estado live a mano, y ve
> calibración, probabilidades, edge y gráficos. **Sin estrategia/EV, sin paper
> trading, sin Polymarket, sin persistencia en base de datos.**

---

## 1. Decisiones tomadas (brainstorming)

| # | Decisión | Elección |
|---|----------|----------|
| 1 | Alcance | **Solo envolver el motor de probabilidades** (sin estrategia, paper trading ni Polymarket) |
| 2 | Estructura | **Multipágina de Streamlit** (`app/pages/`), estado compartido vía `session_state` |
| 3 | Modo de la pantalla live | **Registro de snapshots** (serie de tiempo en memoria de sesión), no una sola foto |
| 4 | Librería de gráficos | **Plotly** (interactivo) |

---

## 2. Alcance

### Dentro
- App Streamlit multipágina con tres vistas: Home, Market Setup, Live Match.
- Setup: ingresar precios 1X2 (+ Over/Under opcional), elegir modelo
  (Poisson / Dixon-Coles), calibrar, ver outputs.
- Live: ingresar estado del partido a mano, ver probabilidades live, edge y
  registrar snapshots que construyen series de tiempo.
- 4 gráficos Plotly.
- Lógica pura testeable separada de la UI.
- Tests: pytest sobre la lógica + `streamlit.testing.v1.AppTest` sobre las páginas.

### Fuera (entregables posteriores)
Matemática de estrategia (EV, señales, edge ejecutable, stops), paper trading,
conexión Polymarket, `XGProvider` real, persistencia en SQLite, backtesting,
alertas, ejecución real. La pantalla live muestra **edge descriptivo**, no
recomendaciones de trade.

---

## 3. Estructura del proyecto

```text
app/
├── dashboard.py              # entrypoint / Home: estado del modelo + instrucciones
└── pages/
    ├── 01_market_setup.py    # precios → calibrar → outputs
    └── 02_live_match.py      # estado live → probabilidades + gráficos
src/dashboard/
├── __init__.py
├── state.py                  # helpers de session_state (guardar/leer modelo y snapshots)
└── logic.py                  # funciones PURAS: build_snapshot, compute_edge, etiqueta, slice de curva
tests/
└── test_dashboard_logic.py   # pytest sobre logic.py + AppTest sobre las páginas
```

- Se ejecuta con `streamlit run app/dashboard.py`.
- Las páginas son **glue delgado**: leen inputs, llaman a `logic.py` y al motor
  (`src/models/*`), y renderizan. Nada de matemática en las páginas.
- Dependencias nuevas: `streamlit`, `plotly` (agregadas a `requirements.txt`).

---

## 4. Componentes

### 4.1 `src/dashboard/state.py` — estado de sesión

Wrappers finos sobre `st.session_state` para no esparcir claves mágicas:

- `save_model(metadata, calibration_result, market_probs, config)` — guarda el
  modelo calibrado y el contexto del partido.
- `get_model() -> dict | None` — devuelve el modelo o `None` si no se ha calibrado.
- `append_snapshot(snapshot: dict)` / `get_snapshots() -> list` / `clear_snapshots()`.

### 4.2 `src/dashboard/logic.py` — lógica pura (testeable sin UI)

- `build_snapshot(model, match_state, market_draw_price, config) -> dict`
  Corre el motor live, calcula probabilidades y edge, y arma el dict del snapshot
  (minuto, marcador, xG home/away, P_home/draw/away modelo, precio empate mercado,
  edge, lambdas restantes). No toca Streamlit.
- `compute_edge(model_draw_prob, market_draw_price) -> float`
  `edge = model_draw_prob − market_draw_price`.
- `describe_edge(edge) -> str`
  Etiqueta **descriptiva factual**, no señal de trade. Ej.: "El modelo ve el
  empate +4.2 pts vs el mercado" / "El modelo ve el empate −1.5 pts vs el
  mercado" / "Modelo y mercado coinciden". (Umbral de "coinciden" configurable,
  p. ej. |edge| < 0.005.)
- `forward_draw_curve(model, config, current_minute) -> list`
  Envuelve `live_update.fair_draw_curve` y devuelve solo los puntos desde el
  minuto actual hasta 90 (la curva forward que se grafica).

### 4.3 `app/dashboard.py` — Home

Título, explicación breve del flujo (Setup → Live), y estado actual: si hay
modelo calibrado en sesión, muestra equipos + lambdas; si no, invita a ir a
Setup. Botón "Reiniciar sesión" que limpia `session_state`.

### 4.4 `app/pages/01_market_setup.py` — Market Setup

**Inputs:**
- Nombre del partido, equipo A (local/favorito), equipo B.
- Precio A, precio empate, precio B.
- Precio Over 2.5 (opcional; si se ingresa, libera `rho` en la calibración).
- Selector de modelo: Poisson / Dixon-Coles.
- (Opcionales, solo se muestran/guardan, sin uso en el cálculo aún): best
  bid/ask, volumen, liquidez, hora de inicio.

**Acción:** botón "Calibrar" → normaliza precios, calibra, guarda el modelo en
`session_state`.

**Outputs:**
- Probabilidades normalizadas (home/draw/away).
- Lambdas calibrados, `rho`, loss, success.
- Advertencias de calibración (si |modelo − mercado| > 0.03 en algún outcome).
- Tabla de marcadores más probables (top 10).
- Over 2.5 del modelo.
- Comparación modelo vs mercado 1X2 (tabla y/o barras Plotly).

### 4.5 `app/pages/02_live_match.py` — Live Match

**Guard:** si no hay modelo en sesión → aviso "Calibra primero en Market Setup"
y `st.stop()`.

**Cabecera:** equipos + lambdas del modelo cargado.

**Inputs:**
- Minuto, marcador home / away.
- xG A, xG B; xG últimos 10 A / B.
- Tiros A/B, tiros al arco A/B (opcionales).
- Tarjetas rojas A / B.
- Precio live del empate en el mercado (para el edge).
- (Opcional) best bid / best ask del empate.

**Cálculo (al cambiar inputs):**
- Probabilidades live P_home/draw/away (condicionadas al marcador actual).
- Lambdas restantes ajustados.
- Precio justo del empate ahora.
- Edge = P_draw modelo − precio de empate de mercado, + etiqueta descriptiva.

**Acciones:** "Registrar snapshot" → agrega a `session_state["snapshots"]`.
Botón "Limpiar snapshots".

**Gráficos (Plotly):**
1. **Curva del precio justo del empate (forward):** del minuto actual a 90,
   asumiendo 0-0. Líneas: P_draw, P_home, P(0-0 final).
2. **Modelo vs mercado en el tiempo:** de los snapshots registrados —
   P_draw del modelo vs precio de empate del mercado, eje x = minuto.
3. **xG acumulado en el tiempo:** home vs away, de los snapshots.
4. **Edge en el tiempo:** edge por minuto, de los snapshots, con línea de
   referencia en 0.

Cada gráfico que depende de snapshots maneja el caso "aún no hay snapshots"
mostrando un mensaje en vez de un gráfico vacío.

---

## 5. Flujo de datos

```text
Setup:
  inputs precios → normalize_prices → calibrate(model) → state.save_model(...)

Live:
  state.get_model()  (guard si None)
    + inputs (MatchState manual, precio empate mercado)
    → logic.build_snapshot → probabilidades live + edge + etiqueta
    → [Registrar] state.append_snapshot
  gráficos:
    forward_draw_curve(model, minuto)         → curva del empate
    state.get_snapshots()                     → series modelo/mercado, xG, edge
```

---

## 6. Testing

### 6.1 Lógica pura (`tests/test_dashboard_logic.py`, pytest)
- `compute_edge`: signo y magnitud correctos.
- `describe_edge`: positivo / negativo / "coinciden" según umbral.
- `build_snapshot`: contiene todos los campos esperados y las probabilidades
  coinciden con llamar al motor directamente; el edge es coherente.
- `forward_draw_curve`: solo incluye minutos ≥ minuto actual y termina en 90.

### 6.2 Páginas (`streamlit.testing.v1.AppTest`)
- Home: corre sin excepción.
- Setup: con inputs válidos (ej. Argentina vs Cabo Verde) y "Calibrar",
  `session_state` queda con un modelo y se muestran lambdas/probabilidades.
- Live sin modelo: muestra el aviso y no crashea.
- Live con modelo: computa probabilidades; "Registrar snapshot" deja la lista
  de snapshots con un elemento.

### 6.3 Verificación manual
- `streamlit run app/dashboard.py` (o boot headless) levanta sin errores.

---

## 7. Fuera de alcance explícito
Estrategia/EV/señales, paper trading, Polymarket, `XGProvider` real, persistencia
SQLite, backtesting, alertas, ejecución real. Cada uno será su propio entregable.
