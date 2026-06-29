"""Pytest config: asegura que la raíz del proyecto esté en sys.path.

Permite que los módulos se importen como `from src.models import poisson`
al correr `pytest` desde la raíz del proyecto.
"""
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
