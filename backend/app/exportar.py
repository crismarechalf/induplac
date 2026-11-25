"""Exportación a CSV (GET /api/exportar/{recurso}).

Reutiliza el mismo filtrado por rol que la consulta (servicio.condicion_vista): cada usuario
descarga solo lo que ya puede ver en pantalla. El CSV está pensado para Excel en Chile:
UTF-8 con BOM, separador ";", decimales con coma y fechas en hora de America/Santiago.
"""
import csv
import io
import json
from collections.abc import Iterator
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import servicio
from .catalogo import NOMBRE_SEDE, NOMBRE_VARIABLE
from .db import Alerta, Auditoria, Incidente, Medicion

RECURSOS = ("mediciones", "alertas", "incidentes", "auditoria")
# Permiso de roles.py que exige cada recurso (None = cualquier usuario, con su vista).
PERMISO = {"mediciones": None, "alertas": None, "incidentes": "incidentes_ver", "auditoria": "auditoria"}
CON_VARIABLE = ("mediciones", "alertas")   # recursos que aceptan el filtro variable
CON_SEDE = ("mediciones", "alertas", "incidentes")

ENCABEZADOS = {
    "mediciones": ["fecha_hora", "sede", "variable", "valor", "unidad"],
    "alertas": ["fecha_hora", "sede", "variable", "nivel", "mensaje", "estado", "fecha_cierre"],
    "incidentes": ["fecha_hora", "sede", "tipo", "descripcion", "registrado_por", "registrado_el"],
    "auditoria": ["fecha_hora", "usuario", "accion", "detalle"],
}

BOM = "﻿"
LOTE = 500  # filas por bloque del streaming


# ---------------------------------------------------------------- formato
def texto(valor) -> str:
    """Celda de texto protegida contra inyección CSV (fórmulas en Excel)."""
    v = "" if valor is None else str(valor)
    return "'" + v if v[:1] in ("=", "+", "-", "@", "\t", "\r") else v


def numero(valor: float) -> str:
    """Decimal con coma y sin ceros de más: 140.5 → 140,5 · 45.0 → 45."""
    return f"{valor:.10g}".replace(".", ",")


def fecha(dt: datetime | None) -> str:
    return servicio._local(dt).strftime("%Y-%m-%d %H:%M") if dt else ""


def _fila(recurso: str, r) -> list[str]:
    if recurso == "mediciones":
        return [fecha(r.ts), NOMBRE_SEDE[r.sede], NOMBRE_VARIABLE[r.variable], numero(r.valor), texto(r.unidad)]
    if recurso == "alertas":
        return [fecha(r.ts), NOMBRE_SEDE[r.sede], NOMBRE_VARIABLE[r.variable], r.nivel, texto(r.mensaje),
                "activa" if r.activa else "cerrada", fecha(r.cerrada_ts)]
    if recurso == "incidentes":
        return [fecha(r.ts), NOMBRE_SEDE[r.sede], texto(r.tipo), texto(r.descripcion), texto(r.registrado_por),
                fecha(r.creado)]
    return [fecha(r.ts), texto(r.usuario), texto(r.accion), texto(json.dumps(r.detalle, ensure_ascii=False))]


# ---------------------------------------------------------------- consultas
def consulta(recurso: str, vista: dict, desde: datetime, hasta: datetime,
             sede: str | None, variable: str | None):
    """SELECT filtrado por rol (vista), período, sede y variable, en orden cronológico."""
    modelo = {"mediciones": Medicion, "alertas": Alerta, "incidentes": Incidente, "auditoria": Auditoria}[recurso]
    q = select(modelo).where(modelo.ts >= desde, modelo.ts <= hasta)
    if recurso in CON_VARIABLE:
        q = q.where(servicio.condicion_vista(modelo, vista))  # mismo filtro que /api/mediciones y /api/alertas
        if variable:
            q = q.where(modelo.variable == variable)
    if sede and recurso in CON_SEDE:
        q = q.where(modelo.sede == sede)
    return q.order_by(modelo.ts, modelo.id)


def contar(s: Session, q) -> int:
    return s.scalar(select(func.count()).select_from(q.order_by(None).subquery()))


def generar_csv(sesion_local, recurso: str, q) -> Iterator[str]:
    """Genera el CSV por bloques, con su propia sesión (vive mientras dura el streaming)."""
    buffer = io.StringIO()
    escritor = csv.writer(buffer, delimiter=";", lineterminator="\r\n")

    def vaciar() -> str:
        contenido = buffer.getvalue()
        buffer.seek(0)
        buffer.truncate()
        return contenido

    escritor.writerow(ENCABEZADOS[recurso])
    yield BOM + vaciar()
    with sesion_local() as s:
        for i, fila in enumerate(s.scalars(q.execution_options(yield_per=LOTE)), start=1):
            escritor.writerow(_fila(recurso, fila))
            if i % LOTE == 0:
                yield vaciar()
    resto = vaciar()
    if resto:
        yield resto
