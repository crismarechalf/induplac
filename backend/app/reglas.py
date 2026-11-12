"""Reglas de negocio de Induplac. Funciones puras: no tocan la base de datos,
para poder probarlas de forma aislada (tests/test_reglas.py).

- Electricidad y agua: CRÍTICO si el consumo de la última hora supera en 20% el
  promedio de esa misma hora y día de la semana en las 4 semanas previas.
- UV: ADVERTENCIA desde 8 y CRÍTICO desde 11 (escala OMS).
- Producción y HH sin incidentes: indicadores, siempre NORMAL.
"""
from datetime import datetime, timedelta

PASO = timedelta(minutes=15)
SEMANA = timedelta(days=7)
SEMANAS_REFERENCIA = 4
UMBRAL_CONSUMO = 1.20
UV_ADVERTENCIA = 8
UV_CRITICO = 11

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def instantes_hora(fin: datetime) -> list[datetime]:
    """Los 4 intervalos de 15 min que forman la hora que termina en `fin`."""
    return [fin - i * PASO for i in range(4)]


def instantes_necesarios(fin: datetime) -> list[datetime]:
    """Todos los instantes que la regla de consumo necesita leer de la base."""
    horas = [fin] + [fin - k * SEMANA for k in range(1, SEMANAS_REFERENCIA + 1)]
    return [t for h in horas for t in instantes_hora(h)]


def consumo_hora(serie: dict[datetime, float], fin: datetime) -> float | None:
    """Suma de los 4 intervalos de la hora. None si falta alguno (hora incompleta)."""
    valores = [serie.get(t) for t in instantes_hora(fin)]
    return None if any(v is None for v in valores) else sum(valores)


def referencia_hora(serie: dict[datetime, float], fin: datetime) -> float | None:
    """Promedio de la misma hora y día de la semana en las 4 semanas previas."""
    previas = [consumo_hora(serie, fin - k * SEMANA) for k in range(1, SEMANAS_REFERENCIA + 1)]
    previas = [c for c in previas if c is not None]
    return sum(previas) / len(previas) if previas else None


def evaluar_consumo(actual: float | None, referencia: float | None) -> str:
    # Sin historial suficiente no se puede afirmar que hay un exceso: se informa normal.
    if actual is None or not referencia:
        return "normal"
    return "critico" if actual > referencia * UMBRAL_CONSUMO else "normal"


def evaluar_uv(valor: float) -> str:
    if valor >= UV_CRITICO:
        return "critico"
    if valor >= UV_ADVERTENCIA:
        return "advertencia"
    return "normal"


def _n(v: float, d: int) -> str:
    texto = f"{v:,.{d}f}"
    return texto.replace(",", "X").replace(".", ",").replace("X", ".")


def mensaje_consumo(actual: float, referencia: float, unidad: str, dia_semana: int, variable: str) -> str:
    d = 0 if variable == "agua" else 1
    exceso = _n((actual / referencia - 1) * 100, 1)
    return (
        f"Consumo de la última hora ({_n(actual, d)} {unidad}) supera en {exceso}% el promedio "
        f"de los {DIAS[dia_semana]} a esta hora en las 4 semanas previas ({_n(referencia, d)} {unidad})."
    )


def mensaje_uv(valor: float, nivel: str) -> str:
    if nivel == "critico":
        return f"Índice UV {_n(valor, 1)}: radiación extrema, evitar trabajos en exteriores."
    return f"Índice UV {_n(valor, 1)}: radiación muy alta, usar protección solar en exteriores."
