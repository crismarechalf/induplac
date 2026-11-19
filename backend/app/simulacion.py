"""Consola de operación y pruebas (rol admin): ajusta cada variable de cada sede.

El estado vive en memoria del proceso: si la API se reinicia, todo vuelve a "Automático".
Cada gateway lo consulta en cada ciclo (GET /api/simulacion/{sede}) y lo aplica a sus medidores:
consumo × (1 + pct/100), producción × pct/100, UV forzado y enlace cortado.
"""
from .catalogo import PUNTOS

# Valor "Automático" de cada control (el gateway mide sin intervenir).
BASE = {"electricidad_pct": 0, "agua_pct": 0, "produccion_pct": 100, "uv_forzado": None, "enlace_cortado": False}

# Control → variable del catálogo que necesita (el enlace existe en todas las sedes).
VARIABLE_DEL_CONTROL = {"electricidad_pct": "electricidad", "agua_pct": "agua",
                        "produccion_pct": "produccion", "uv_forzado": "uv"}

_estado: dict[str, dict] = {}


def controles(sede: str) -> list[str]:
    """Controles que existen en la sede (la Oficina RM no tiene producción ni UV)."""
    return [c for c in BASE if VARIABLE_DEL_CONTROL.get(c) in PUNTOS[sede] or c == "enlace_cortado"]


def restablecer() -> None:
    _estado.clear()
    for sede in PUNTOS:
        _estado[sede] = {c: BASE[c] for c in controles(sede)}


def de_sede(sede: str) -> dict:
    return dict(_estado[sede])


def todas() -> dict:
    return {sede: de_sede(sede) for sede in PUNTOS}


def aplicar(sede: str, cambios: dict) -> dict:
    """Aplica los cambios (ya validados por rango y catálogo) y devuelve el estado de la sede."""
    _estado[sede].update(cambios)
    return de_sede(sede)


restablecer()
