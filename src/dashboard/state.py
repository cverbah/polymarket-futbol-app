"""Estado de sesión: wrappers finos sobre `st.session_state`.

Centraliza las claves para no esparcir strings mágicos por las páginas.
Estas funciones solo tocan `st.session_state`, que funciona tanto en runtime
como bajo `streamlit.testing.v1.AppTest`.

Forma del dict MODEL guardado en sesión (lo consume la capa de páginas):
    {
        "metadata": {"home_team": str, "away_team": str, "match_name": str},
        "model_type": "poisson" | "dixon_coles",
        "lambda_home": float,
        "lambda_away": float,
        "rho": float,
        "market_probs": {"home": float, "draw": float, "away": float},
        "config": dict,
    }
"""
from __future__ import annotations

import streamlit as st

# Claves centralizadas de session_state.
MODEL_KEY = "model"
SNAPSHOTS_KEY = "snapshots"
SERIES_KEY = "live_series"
SERIES_SLUG_KEY = "live_series_slug"


def save_model(
    metadata: dict,
    calibration_result: dict,
    market_probs: dict,
    config: dict,
) -> None:
    """Guarda el modelo calibrado y el contexto del partido en la sesión.

    Extrae lambdas y rho del resultado de calibración.
    """
    st.session_state[MODEL_KEY] = {
        "metadata": metadata,
        "model_type": metadata.get("model_type", "poisson"),
        "lambda_home": calibration_result["lambda_home"],
        "lambda_away": calibration_result["lambda_away"],
        "rho": calibration_result["rho"],
        "market_probs": market_probs,
        "config": config,
    }


def get_model() -> dict | None:
    """Devuelve el modelo guardado, o None si aún no se ha calibrado."""
    return st.session_state.get(MODEL_KEY)


def append_snapshot(snapshot: dict) -> None:
    """Agrega un snapshot a la serie en memoria de la sesión."""
    if SNAPSHOTS_KEY not in st.session_state:
        st.session_state[SNAPSHOTS_KEY] = []
    st.session_state[SNAPSHOTS_KEY].append(snapshot)


def get_snapshots() -> list:
    """Devuelve la lista de snapshots registrados (vacía si no hay)."""
    if SNAPSHOTS_KEY not in st.session_state:
        st.session_state[SNAPSHOTS_KEY] = []
    return st.session_state[SNAPSHOTS_KEY]


def clear_snapshots() -> None:
    """Limpia la serie de snapshots."""
    st.session_state[SNAPSHOTS_KEY] = []


def reset_session() -> None:
    """Limpia el modelo y los snapshots de la sesión."""
    st.session_state.pop(MODEL_KEY, None)
    st.session_state[SNAPSHOTS_KEY] = []


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
