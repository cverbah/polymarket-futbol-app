# Diseño — Live Match auto-refrescado (auto-tracking en vivo)

**Fecha:** 2026-06-30
**Estado:** implementado (2026-06-30).
**Entregable:** mejora del Live Match (Fase posterior a Entregable D).

## 1. Contexto y objetivo

Hoy la página **Live Match** (`app/pages/02_live_match.py`) es 100% manual: el
usuario teclea minuto, marcador, xG, tiros, tarjetas y el precio del empate, y
registra cada snapshot a mano con un botón. Solo grafica el empate.

**Objetivo:** convertir Live Match en el **monitor en vivo automático** del
partido que se está analizando. Se auto-refresca, sondea las APIs (las mismas que
ya usa Market Setup), va acumulando una serie temporal sin intervención del
usuario, y presenta visualizaciones más dinámicas (no solo el empate).

**Flujo de uso:** se analiza **un partido a la vez**. En Market Setup se elige el
partido y se calibra el modelo; Live Match es la otra vista del **mismo** partido
y se "activa" para ir llevando los datos automáticamente mientras avanza.

## 2. Alcance

**Dentro:**
- Captura automática por timer (minuto, marcador, precios 1X2/O-U/BTTS) vía el
  connector existente.
- Acumulación automática de snapshots en una serie temporal en sesión, atada al
  `slug` del partido (se reinicia si cambia el partido).
- Scoreboard en vivo + controles (auto on/off, intervalo, actualizar ahora,
  reiniciar serie) + KPIs.
- **Gráfico A**: win-probability — P(gana local) / P(empate) / P(gana visita) del
  resultado **final** en el tiempo, con marcas verticales en cada gol.
- **Gráfico C**: escáner de edge multi-mercado (barras por mercado, ordenadas por
  |edge|).
- Auto-stop al terminar el partido (`status == post`).

**Fuera (explícito):**
- **xG en vivo**: no existe fuente gratuita confiable para el Mundial (las de pago
  como Sportmonks/TheStatsAPI van contra el enfoque lean; las gratis —API-Football
  free, FotMob no oficial— tienen cuota insuficiente o son frágiles). Se **difiere**.
  El motor ya ajusta los λ restantes con minuto + marcador + precio del mercado.
- Persistencia en disco (SQLite): queda para el entregable de storage. La serie
  vive en memoria de sesión.
- Tarjetas rojas en vivo: no hay fuente automática; se asumen 0 (override futuro).
- Ejecución / paper trading / señales de trade.

## 3. Decisiones de diseño (validadas en brainstorming)

| Tema | Decisión |
|---|---|
| Captura | **Auto-refresco por timer** (nativo `st.fragment(run_every=...)`, sin libs nuevas). |
| xG | **Diferido**; Live Match 100% automático sin xG. |
| Dependencia | Reutiliza el **modelo calibrado en Market Setup** (sus λ como prior) y su `slug`. |
| Serie | Atada al `slug`; se **reinicia** al cambiar de partido. En memoria de sesión. |
| Gráfico A | **A1**: 3 líneas de outcome final (local/empate/visita) + marcas de gol. |
| Gráfico C | Escáner de edge multi-mercado, barras ordenadas por |edge|. |
| Fin de partido | **Auto-stop** en `post`; espera en `pre`. |

## 4. Arquitectura y flujo de datos

En cada tick (cada `live_refresh_seconds`, default 30s):

```
modelo guardado (Market Setup): λ prior, rho, model_type, metadata.slug
                 │
                 ▼
   connector.get_match_markets(slug)
   → MatchMarkets { one_x_two, over_under, btts, live(minuto/marcador/status) }
                 │
                 ▼
   logic.build_live_snapshot(model, match_markets, config)
     1. MatchState desde mm.live (minuto, marcador; xG=None, rojas=0)
     2. live_update.live_outcome_probs(λ prior, state, ...) → P(local/empate/visita) final
     3. matriz del marcador final (analytics.final_score_matrix) + λ restantes
     4. analytics.model_vs_market(matriz, λ_rem, quotes de mm) → edge por mercado
     → snapshot { minuto, marcador, status, probs 1X2, precios mercado,
                  edges[], mejor_oportunidad, timestamp }
                 │
                 ▼
   state.append_live_snapshot(slug, snapshot)   (reinicia serie si cambió slug)
                 │
                 ▼
   render: scoreboard + KPIs + Gráfico A + Gráfico C
```

**Nota de modelado (prior):** `build_live_snapshot` usa los λ guardados como el
prior de partido completo y el motor `live_update` los escala al tiempo restante
y los condiciona al marcador. Esto mantiene el **modelo independiente del precio
live**, de modo que el edge (modelo − mercado) sea informativo (si calibráramos
al precio live cada tick, el edge sería ~0 por construcción). Supuesto: Market
Setup se calibró del partido en análisis (idealmente pre-partido, el flujo
natural). Es la misma mecánica que el `build_snapshot` actual, generalizada.

## 5. Layout de la página (de arriba a abajo)

1. **Scoreboard** (auto): pill de estado (pre/live/HT/post) · `Local  H – A  Visita`
   (marcador grande) · minuto. Reusa el estilo del banner de Market Setup.
2. **Controles**: `Auto: ON ⏱ 30s` (toggle) · `Pausar` · `Actualizar ahora` ·
   `Reiniciar serie` · a la derecha: `última actualización HH:MM:SS · N snapshots`.
3. **KPIs** (5 tiles): `P(local)` · `P(empate)` · `P(visita)` (probs del modelo) ·
   **`Edge empate`** (destacado, con flecha 🟢/🔴) · `Mejor oportunidad`
   (mercado con mayor |edge|).
4. **Gráfico A** — win-probability en el tiempo (3 líneas + marcas de gol).
5. **Gráfico C** — escáner de edge por mercado (barras divergentes desde 0).

**Estados especiales:**
- `pre`: scoreboard "Aún no comienza"; no se agregan snapshots; gráficos vacíos
  con nota "esperando el inicio".
- `post`: scoreboard "Finalizado H–A"; auto-refresco detenido; se muestra la serie
  completa acumulada.
- Sin modelo en sesión: warning "Calibra primero en Market Setup" + `st.stop()`.

## 6. Especificación de los gráficos

**Gráfico A — win-probability (Plotly líneas):**
- Eje X: minuto del snapshot. Eje Y: probabilidad (0–1).
- 3 trazas: `P(gana <local>)` (azul), `P(empate)` (ámbar), `P(gana <visita>)`
  (rojo). Son las probabilidades del **resultado final** proyectado desde el
  marcador actual (vecindario implícito en el modelo).
- **Marcas de gol**: línea vertical punteada en los minutos donde el marcador
  cambió entre snapshots consecutivos, anotada con el nuevo marcador (p. ej. ⚽1-0).

**Gráfico C — escáner de edge multi-mercado (Plotly barras horizontales):**
- Una barra por mercado disponible: `home`, `draw`, `away`, `over_<línea>` por cada
  línea en `analytics.SUPPORTED_OU_LINES` presente, y `btts`.
- Valor = edge = P(modelo) − precio(mercado), en puntos. Barra divergente desde 0;
  **verde** si edge > 0 (modelo lo ve barato), **rojo** si < 0 (caro).
- Ordenadas por |edge| descendente. Reusa `analytics.model_vs_market`.

## 7. Unidades de código (cambios por archivo)

- **`src/connectors/polymarket.py`** — sin cambios. `get_match_markets(slug)` ya
  devuelve precios + `live` (minuto/marcador/status), con fallback ESPN disponible.

- **`src/dashboard/logic.py`** (puro, sin streamlit):
  - **Nueva** `build_live_snapshot(model, match_markets, config) -> dict`: arma el
    `MatchState` desde `mm.live`, corre el motor live, calcula probs 1X2 finales y
    **edge por mercado** (vía `analytics.model_vs_market`), y devuelve el snapshot.
  - **Nueva** helper opcional `goal_markers(series) -> list`: deriva los puntos
    donde cambió el marcador (para el Gráfico A).
  - Se **eliminan** `forward_draw_curve` y el `build_snapshot` manual (obsoletos).
    `compute_edge` / `describe_edge` se mantienen (siguen útiles para el KPI del
    empate).

- **`src/dashboard/state.py`**:
  - Serie atada al partido. **Nuevas**: `append_live_snapshot(slug, snap)` (reinicia
    si el slug guardado difiere), `get_series()`, `reset_series()`. Se conserva la
    clave de snapshots pero con awareness de `slug` (nueva clave `SERIES_SLUG_KEY`).

- **`app/pages/02_live_match.py`** — **reescritura**:
  - Guard de modelo. Lee `slug` desde `model["metadata"]["slug"]`.
  - `@st.fragment(run_every = intervalo if auto_on else None)` que sondea, agrega y
    redibuja scoreboard + KPIs + gráficos. Botón "Actualizar ahora" = tick manual.
  - Fuera: todos los `number_input` manuales y el botón "Registrar snapshot".
  - Manejo de error de red por tick: warning + conserva la serie (no se cae).

- **`config.yaml`** (bloque `polymarket:` o nuevo `live:`): `live_refresh_seconds: 30`.

## 8. Mecanismo de auto-refresco

- `st.fragment(run_every=...)`: solo el fragmento del panel live se re-ejecuta cada
  tick; el resto de la página no. `run_every=None` cuando Auto está OFF (pausado).
- El toggle Auto y el intervalo son widgets; al cambiarlos se re-ejecuta el script
  completo y se redefine el fragmento con el nuevo `run_every`.
- Dentro del fragmento, la lectura de mercados es **fresca cada tick** (llamada
  directa a `pm.get_match_markets`, sin cache, para no servir datos viejos).

## 9. Manejo de errores y casos borde

- **Red caída en un tick**: capturar `PolymarketError`/excepción de red → `st.warning`
  y mantener el último snapshot/serie. No interrumpe el auto-refresco.
- **Minuto `None` en vivo** (ESPN sin reloj): se grafica el snapshot igual; el eje X
  usa el minuto disponible o, si falta, el índice del snapshot (degradación suave).
- **Cambio de partido en Market Setup**: al primer tick con un `slug` distinto al de
  la serie, `append_live_snapshot` reinicia la serie.
- **Snapshots duplicados**: se agrega un snapshot por tick; los gráficos toleran
  puntos con el mismo minuto (el tiempo real avanza por timestamp).

## 10. Testing (TDD)

**Puro (`tests/test_dashboard_logic.py`):**
- `build_live_snapshot` con fixtures reales (`wc_match_main` live 0-0,
  `wc_match_live_scored` 1-1, `wc_match_post`): verifica probs 1X2 (suman ~1, signo
  del favorito), edge por mercado presente y coherente, y mejor oportunidad.
- `goal_markers`: detecta correctamente los cambios de marcador en una serie.

**Estado (`tests/test_dashboard_*` o nuevo):**
- `append_live_snapshot` reinicia la serie al cambiar `slug`; acumula con el mismo.

**Página (`tests/test_live_match_page.py`, AppTest):**
- Con modelo en sesión (vía `state.save_model`) + `pm.get_match_markets` mockeado:
  el scoreboard muestra marcador/minuto; los KPIs muestran las 3 probabilidades;
  existen el Gráfico A y el Gráfico C.
- **Acumulación**: `.run()` sucesivos con estados que evolucionan (0-0 → 1-1)
  agregan snapshots a la serie.
- **Auto-stop** en `post`: no agrega más snapshots y muestra resultado final.
- Se actualizan/retiran los tests que cubrían inputs manuales y `forward_draw_curve`.

## 11. Futuro (anotado, fuera de alcance)

- xG en vivo si aparece fuente confiable (o de pago, ya monetizando) → override de
  los λ restantes (el motor ya lo soporta).
- Persistencia de la serie en SQLite (entregable de storage) para histórico y
  backtesting.
- Tarjetas rojas / eventos en vivo si hay fuente automática.
