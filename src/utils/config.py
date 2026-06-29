"""Carga de parametros del modelo desde config.yaml.

Todos los parametros viven en config.yaml (no hardcodeados). Esta funcion
devuelve el bloque `model:` como un dict.
"""
from __future__ import annotations

import os
import yaml

_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "config.yaml",
)


def load_config(path: str = _CONFIG_PATH) -> dict:
    """Carga el bloque `model:` de config.yaml como dict."""
    with open(path, "r") as f:
        data = yaml.safe_load(f)
    return data["model"]
