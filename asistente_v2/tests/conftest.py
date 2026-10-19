"""Pone el directorio asistente_v2/ en sys.path para que
`config`, `core` y `actions` sean importables desde los tests,
igual que cuando la app corre desde asistente_v2/.
"""
import os
import sys

ASISTENTE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ASISTENTE_DIR not in sys.path:
    sys.path.insert(0, ASISTENTE_DIR)
