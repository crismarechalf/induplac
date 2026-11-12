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
        puntos = PUNTOS[self.sede]
        vistas = set()
        for m in self.mediciones:
            if m.variable not in puntos:
                raise ValueError(f"{m.variable} no se mide en {self.sede}")
            if m.variable in vistas:
                raise ValueError(f"{m.variable} viene repetida en el lote")
            vistas.add(m.variable)
            if m.unidad != puntos[m.variable]:
                raise ValueError(f"{m.variable}: unidad {m.unidad!r}, se esperaba {puntos[m.variable]!r}")
            minimo, maximo = RANGO_VALIDO[m.variable]
            if not math.isfinite(m.valor) or not (minimo <= m.valor <= maximo):
                raise ValueError(f"{m.variable}: valor {m.valor} fuera de rango [{minimo}, {maximo}]")
        return self


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
