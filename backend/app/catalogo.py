"""Catálogo de puntos de medición de Induplac (8 en total).

Es la única fuente de verdad sobre qué variable existe en qué sede y con qué
unidad. La validación de los lotes y las reglas se apoyan en este archivo.
"""

PUNTOS: dict[str, dict[str, str]] = {
    "oficina_rm": {"electricidad": "kWh", "agua": "L", "hh_sin_incidentes": "h"},
    "planta": {
        "electricidad": "kWh",
        "agua": "L",
        "produccion": "tableros",
        "hh_sin_incidentes": "h",
        "uv": "índice",
    },
}

SEDES = tuple(PUNTOS)
VARIABLES_CONSUMO = ("electricidad", "agua")

# Rango físicamente posible por variable (para rechazar lecturas absurdas).
# Un valor fuera de rango indica un medidor dañado o un error de transmisión.
RANGO_VALIDO: dict[str, tuple[float, float]] = {
    "electricidad": (0, 5_000),        # kWh por intervalo de 15 min
    "agua": (0, 50_000),               # litros por intervalo de 15 min
    "produccion": (0, 1_000),          # tableros por intervalo
    "hh_sin_incidentes": (0, 10_000_000),
    "uv": (0, 20),                     # escala OMS llega a 11+; 20 es tope físico
}

NOMBRE_VARIABLE = {
    "electricidad": "Electricidad",
    "agua": "Agua",
    "produccion": "Producción",
    "hh_sin_incidentes": "HH sin incidentes",
    "uv": "Índice UV",
}
NOMBRE_SEDE = {"oficina_rm": "Oficina RM", "planta": "Planta Valparaíso"}
