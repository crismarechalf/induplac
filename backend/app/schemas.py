"""Contrato de entrada (validación de lotes) y de salida de la API REST."""
import math
from datetime import datetime, timezone

from pydantic import BaseModel, Field, field_validator, model_validator

from .catalogo import PUNTOS, RANGO_VALIDO


class MedicionEntrada(BaseModel):
    variable: str
    valor: float
    unidad: str


class LoteEntrada(BaseModel):
    """Lote que envía el gateway de una sede en cada ciclo."""
    sede: str = Field(examples=["planta"])
    ts: datetime = Field(examples=["2026-11-20T18:00:00Z"])
    mediciones: list[MedicionEntrada] = Field(min_length=1)

    @field_validator("sede")
    @classmethod
    def sede_conocida(cls, v: str) -> str:
        if v not in PUNTOS:
            raise ValueError(f"sede desconocida: {v}")
        return v

    @field_validator("ts")
    @classmethod
    def a_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("ts debe incluir zona horaria (ISO 8601 con Z u offset)")
        return v.astimezone(timezone.utc).replace(tzinfo=None)

    @model_validator(mode="after")
    def mediciones_validas(self):
        vistas = set()
        for m in self.mediciones:
            if m.variable in vistas:
                raise ValueError(f"{m.variable} viene repetida en el lote")
            vistas.add(m.variable)
            error = error_medicion(self.sede, m.variable, m.unidad, m.valor)
            if error:
                raise ValueError(error)
        return self


def error_medicion(sede: str, variable: str, unidad: str, valor: float) -> str | None:
    """Reglas de una medición según el catálogo (las usan los lotes del gateway y la carga manual).

    Devuelve el motivo en palabras, o None si es válida.
    """
    puntos = PUNTOS[sede]
    if variable not in puntos:
        return f"{variable} no se mide en {sede}"
    if unidad != puntos[variable]:
        return f"{variable}: unidad {unidad!r}, se esperaba {puntos[variable]!r}"
    minimo, maximo = RANGO_VALIDO[variable]
    if not math.isfinite(valor) or not (minimo <= valor <= maximo):
        return f"{variable}: valor {valor:g} fuera de rango [{minimo}, {maximo}]"
    return None


class ResultadoIngesta(BaseModel):
    aceptados: int
    descartados: int = Field(description="Lotes duplicados o atrasados (ya recibidos)")


class TokenEntrada(BaseModel):
    gateway_id: str
    secreto: str


class TokenSalida(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expira_en: int
