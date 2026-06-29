"""Carga de parametros desde config.yaml.

Todos los parametros viven en config.yaml (no hardcodeados). Por defecto esta
funcion devuelve el bloque `model:` (comportamiento historico), pero acepta un
parametro `section` para leer otros bloques (p. ej. `polymarket:`).
"""
from __future__ import annotations

import os
import yaml

_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "config.yaml",
)


def load_config(path: str = _CONFIG_PATH, section: str = "model") -> dict:
    """Carga un bloque de config.yaml como dict.

    Por compatibilidad, `section` es "model" por defecto, asi que
    `load_config()` sigue devolviendo el bloque del modelo. Pasa
    `section="polymarket"` para leer la config del conector.
    """
    with open(path, "r") as f:
        data = yaml.safe_load(f)
    return data[section]
