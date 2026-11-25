"""Procesamiento de lotes: deduplicación, almacenamiento, evaluación de reglas,
estado actual y ciclo de vida de las alertas.

Flujo por lote:  validar (schemas) → descartar duplicados → guardar → evaluar
reglas → actualizar estado_actual → abrir/cerrar alertas → eventos WebSocket.
"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import and_, delete, false, func, or_, select
from sqlalchemy.orm import Session

from . import config, reglas
from .catalogo import PISO_EXCESO, PUNTOS, TURNO, VARIABLES_CONSUMO
from .db import Alerta, Auditoria, Config, EstadoActual, Incidente, Lote, Medicion
from .schemas import LoteEntrada

ZONA = ZoneInfo(config.ZONA)


# ---------------------------------------------------------------- utilidades
def ahora_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat() + "Z"


def _local(dt_utc: datetime) -> datetime:
    return dt_utc.replace(tzinfo=timezone.utc).astimezone(ZONA)


def _a_utc(dt_local: datetime) -> datetime:
    return dt_local.astimezone(timezone.utc).replace(tzinfo=None)


def inicio_dia(ts: datetime) -> datetime:
    return _a_utc(_local(ts).replace(hour=0, minute=0, second=0, microsecond=0))


def inicio_mes(ts: datetime) -> datetime:
    return _a_utc(_local(ts).replace(day=1, hour=0, minute=0, second=0, microsecond=0))


def estado_a_dict(e: EstadoActual) -> dict:
    return {"sede": e.sede, "variable": e.variable, "valor": e.valor, "unidad": e.unidad,
            "estado": e.estado, "ts": iso(e.ts), **(e.extras or {})}


def alerta_a_dict(a: Alerta) -> dict:
    return {"id": str(a.id), "sede": a.sede, "variable": a.variable, "nivel": a.nivel,
            "mensaje": a.mensaje, "ts": iso(a.ts), "activa": a.activa}


# ------------------------------------------------------------ reglas con datos
def _serie(s: Session, sede: str, variable: str, instantes: list[datetime]) -> dict[datetime, float]:
    filas = s.execute(
        select(Medicion.ts, Medicion.valor).where(
            Medicion.sede == sede, Medicion.variable == variable, Medicion.ts.in_(instantes))
    ).all()
    return {ts: valor for ts, valor in filas}


def _evaluar(s: Session, sede: str, variable: str, valor: float, unidad: str, ts: datetime):
    """Devuelve (estado, mensaje_alerta, extras)."""
    if variable in VARIABLES_CONSUMO:
        serie = _serie(s, sede, variable, reglas.instantes_necesarios(ts))
        actual = reglas.consumo_hora(serie, ts)
        referencia = reglas.referencia_hora(serie, ts)
        estado = reglas.evaluar_consumo(actual, referencia, PISO_EXCESO.get((sede, variable), 0))
        mensaje = (reglas.mensaje_consumo(actual, referencia, unidad, _local(ts).weekday(), variable)
                   if estado != "normal" else "")
        return estado, mensaje, {}

    if variable == "uv":
        estado = reglas.evaluar_uv(valor)
        maximo = s.scalar(select(func.max(Medicion.valor)).where(
            Medicion.sede == sede, Medicion.variable == "uv",
            Medicion.ts >= inicio_dia(ts), Medicion.ts <= ts))
        return estado, reglas.mensaje_uv(valor, estado), {"max_dia": maximo if maximo is not None else valor}

    if variable == "produccion":
        def suma(desde):
            return s.scalar(select(func.coalesce(func.sum(Medicion.valor), 0)).where(
                Medicion.sede == sede, Medicion.variable == "produccion",
                Medicion.ts >= desde, Medicion.ts <= ts))
        # Línea detenida: las 2 últimas lecturas (la actual ya está guardada), en hora local.
        filas = s.execute(select(Medicion.ts, Medicion.valor).where(
            Medicion.sede == sede, Medicion.variable == "produccion", Medicion.ts <= ts)
            .order_by(Medicion.ts.desc()).limit(2)).all()
        lecturas = [(_local(t), v, reglas.en_turno(TURNO[sede], _local(t))) for t, v in reversed(filas)]
        estado, desde = reglas.evaluar_produccion(lecturas)
        mensaje = reglas.mensaje_linea_detenida(desde) if desde else ""
        return estado, mensaje, {"acumulado_dia": suma(inicio_dia(ts)), "acumulado_mes": suma(inicio_mes(ts))}

    return "normal", "", {}  # hh_sin_incidentes: indicador


def _actualizar_alerta(s: Session, sede, variable, estado, mensaje, ts, eventos, nuevas):
    abierta = s.scalar(select(Alerta).where(
        Alerta.sede == sede, Alerta.variable == variable, Alerta.activa.is_(True)))
    if estado in ("advertencia", "critico"):
        if abierta and abierta.nivel == estado:
            return
        if abierta:
            abierta.activa, abierta.cerrada_ts = False, ts
            eventos.append({"tipo": "alerta", "data": alerta_a_dict(abierta)})
        nueva = Alerta(sede=sede, variable=variable, nivel=estado, mensaje=mensaje, ts=ts, activa=True)
        s.add(nueva)
        s.flush()
        eventos.append({"tipo": "alerta", "data": alerta_a_dict(nueva)})
        nuevas.append(nueva)
    elif abierta:
        abierta.activa, abierta.cerrada_ts = False, ts
        eventos.append({"tipo": "alerta", "data": alerta_a_dict(abierta)})


# ------------------------------------------------------------------- ingesta
def ultimo_ts_sede(s: Session, sede: str) -> datetime | None:
    return s.scalar(select(func.max(Lote.ts)).where(Lote.sede == sede))


def ingerir(s: Session, lotes: list[LoteEntrada], gateway_id: str):
    """Procesa uno o varios lotes (los reenvíos tras un corte llegan juntos y en orden).

    Devuelve (aceptados, descartados, eventos_websocket, alertas_nuevas).
    """
    aceptados = descartados = 0
    eventos: list[dict] = []
    nuevas: list[Alerta] = []
    ultimo: dict[str, datetime | None] = {}
    estado_final: dict[tuple, EstadoActual] = {}
    recibido = ahora_utc()

    for lote in sorted(lotes, key=lambda l: l.ts):
        if lote.sede not in ultimo:
            ultimo[lote.sede] = ultimo_ts_sede(s, lote.sede)
        # Deduplicación: solo se acepta un lote más nuevo que el último de esa sede.
        if ultimo[lote.sede] is not None and lote.ts <= ultimo[lote.sede]:
            descartados += 1
            continue
        ultimo[lote.sede] = lote.ts

        registro = Lote(sede=lote.sede, ts=lote.ts, recibido=recibido, gateway=gateway_id)
        s.add(registro)
        s.flush()
        for m in lote.mediciones:
            s.add(Medicion(lote_id=registro.id, sede=lote.sede, variable=m.variable,
                           valor=m.valor, unidad=m.unidad, ts=lote.ts))
        s.flush()

        for m in lote.mediciones:
            estado, mensaje, extras = _evaluar(s, lote.sede, m.variable, m.valor, m.unidad, lote.ts)
            fila = s.get(EstadoActual, (lote.sede, m.variable)) or EstadoActual(sede=lote.sede, variable=m.variable)
            fila.valor, fila.unidad, fila.estado, fila.ts, fila.extras = m.valor, m.unidad, estado, lote.ts, extras
            s.add(fila)
            estado_final[(lote.sede, m.variable)] = fila
            _actualizar_alerta(s, lote.sede, m.variable, estado, mensaje, lote.ts, eventos, nuevas)
        aceptados += 1

    s.commit()
    if estado_final:
        eventos.append({"tipo": "estado", "data": [estado_a_dict(e) for e in estado_final.values()]})
    return aceptados, descartados, eventos, nuevas


# --------------------------------------------------------------- sin datos
def ultimo_recibido(s: Session) -> dict[str, datetime]:
    filas = s.execute(select(Lote.sede, func.max(Lote.recibido)).group_by(Lote.sede)).all()
    return {sede: r for sede, r in filas}


def sedes_sin_datos(s: Session, ahora: datetime | None = None) -> set[str]:
    """Sedes cuyo gateway no envía lotes hace más de 2 ciclos."""
    ahora = ahora or ahora_utc()
    limite = timedelta(seconds=config.CICLO_SEG * config.CICLOS_SIN_DATOS)
    recibidos = ultimo_recibido(s)
    return {sede for sede in PUNTOS if sede in recibidos and ahora - recibidos[sede] > limite}


def estado_actual(s: Session, sin_datos: set[str] | None = None, vista: dict | None = None) -> list[dict]:
    """Estado de los puntos de medición; con `vista`, solo los que ese rol puede ver."""
    sin_datos = sedes_sin_datos(s) if sin_datos is None else sin_datos
    filas = {(e.sede, e.variable): e for e in s.scalars(select(EstadoActual))}
    salida = []
    for sede, variables in (vista or PUNTOS).items():
        for variable in variables:
            e = filas.get((sede, variable))
            if not e:
                continue
            item = estado_a_dict(e)
            if sede in sin_datos:
                item["estado"] = "sin_datos"  # ts queda en la hora del último lote recibido
            salida.append(item)
    return salida


# ---------------------------------------------------------------- retención
def podar(s: Session) -> int:
    """Borra mediciones y lotes con ts más antiguo que RETENCION_DIAS antes de la lectura más nueva.

    Se mide contra el reloj de las lecturas (simulado en la demo, donde 1 día real
    son ~300 días simulados). Conserva siempre las 4 semanas que usa la regla de consumo.
    """
    ultimo = s.scalar(select(func.max(Lote.ts)))
    if ultimo is None:
        return 0
    limite = ultimo - timedelta(days=config.RETENCION_DIAS)
    borradas = s.execute(delete(Medicion).where(Medicion.ts < limite)).rowcount
    # Las mediciones de un lote comparten su ts: primero se borran ellas y luego el lote.
    s.execute(delete(Lote).where(Lote.ts < limite))
    s.commit()
    return borradas


# ---------------------------------------------------------------- filtrado por rol
def condicion_vista(modelo, vista: dict):
    """WHERE (sede, variable) visible para el rol."""
    return or_(*(and_(modelo.sede == sede, modelo.variable.in_(variables)) for sede, variables in vista.items())) \
        if vista else false()


def alertas(s: Session, vista: dict, activas: bool | None, limite: int) -> list[dict]:
    q = select(Alerta).where(condicion_vista(Alerta, vista)).order_by(Alerta.ts.desc()).limit(limite)
    if activas is not None:
        q = q.where(Alerta.activa.is_(activas))
    return [alerta_a_dict(a) for a in s.scalars(q)]


def mediciones(s: Session, vista: dict, sede: str | None, variable: str | None,
               desde: datetime | None, limite: int) -> list[dict]:
    q = select(Medicion).where(condicion_vista(Medicion, vista))
    if sede:
        q = q.where(Medicion.sede == sede)
    if variable:
        q = q.where(Medicion.variable == variable)
    if desde:
        q = q.where(Medicion.ts >= desde)
    # Las más recientes primero para respetar el límite, y luego en orden cronológico.
    filas = list(s.scalars(q.order_by(Medicion.ts.desc()).limit(limite)))[::-1]
    return [{"sede": m.sede, "variable": m.variable, "valor": m.valor, "unidad": m.unidad, "ts": iso(m.ts)}
            for m in filas]


# ---------------------------------------------------------------- reloj de simulación único
PASO = timedelta(minutes=15)


def piso_15min(dt: datetime) -> datetime:
    return dt.replace(minute=dt.minute - dt.minute % 15, second=0, microsecond=0)


def _config(s: Session, clave: str) -> str | None:
    fila = s.get(Config, clave)
    return fila.valor if fila else None


def iniciar_reloj(s: Session) -> None:
    """En cada arranque de la API ancla el reloj: hora simulada = justo después del último lote.

    Así el tiempo con la instancia detenida (Learner Lab apagado) no hace avanzar la
    simulación: si avanzara (×300 en la demo), al volver no habría lecturas de las 4 semanas
    previas y la regla de consumo no tendría referencia. Tampoco hay saltos atrás.
    Sin lecturas todavía, arranca en la hora real.
    """
    ahora = ahora_utc()
    ultimo = s.scalar(select(func.max(Lote.ts)))
    inicio_sim = max(piso_15min(ahora), ultimo + PASO) if ultimo else piso_15min(ahora)
    for clave, valor in (("reloj_inicio_real", ahora), ("reloj_inicio_sim", inicio_sim)):
        s.merge(Config(clave=clave, valor=valor.isoformat()))
    s.commit()


def factor_reloj() -> float:
    """Minutos simulados por minuto real: 1 ciclo (CICLO_SEG reales) = 15 min."""
    return 900 / config.CICLO_SEG if config.CICLO_SEG else 1.0


def hora_simulada(s: Session) -> datetime:
    inicio_real = datetime.fromisoformat(_config(s, "reloj_inicio_real"))
    inicio_sim = datetime.fromisoformat(_config(s, "reloj_inicio_sim"))
    return inicio_sim + (ahora_utc() - inicio_real) * factor_reloj()


# ---------------------------------------------------------------- incidentes
TIPOS_INCIDENTE = ("Accidente con tiempo perdido", "Accidente sin tiempo perdido", "Cuasi accidente")


def incidente_a_dict(i: Incidente) -> dict:
    return {"id": str(i.id), "sede": i.sede, "ts": iso(i.ts), "tipo": i.tipo,
            "descripcion": i.descripcion, "registrado_por": i.registrado_por}


def conteo_incidentes(s: Session, sede: str) -> int:
    """Lo usa el gateway como incidente_id: si sube, reinicia sus HH sin incidentes."""
    return s.scalar(select(func.count()).select_from(Incidente).where(Incidente.sede == sede))


def incidentes(s: Session, limite: int) -> list[dict]:
    q = select(Incidente).order_by(Incidente.ts.desc(), Incidente.id.desc()).limit(limite)
    return [incidente_a_dict(i) for i in s.scalars(q)]


# ---------------------------------------------------------------- auditoría
def auditar(s: Session, usuario: str, accion: str, detalle: dict | None = None) -> None:
    s.add(Auditoria(ts=ahora_utc(), usuario=usuario, accion=accion, detalle=detalle or {}))
    s.commit()


def auditoria(s: Session, limite: int, acciones: tuple[str, ...] | None = None) -> list[dict]:
    q = select(Auditoria).order_by(Auditoria.ts.desc(), Auditoria.id.desc()).limit(limite)
    if acciones:
        q = q.where(Auditoria.accion.in_(acciones))
    return [{"ts": iso(a.ts), "usuario": a.usuario, "accion": a.accion, "detalle": a.detalle} for a in s.scalars(q)]
