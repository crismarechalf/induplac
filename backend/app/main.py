"""API REST + WebSocket de Induplac (FastAPI).

Endpoints:
  POST /api/auth/token   gateway → token JWT
  POST /api/lotes        gateway → lote(s) de mediciones           [requiere Bearer]
  GET  /api/estado       dashboard ← último valor y estado de cada punto
  GET  /api/alertas      dashboard ← alertas (activas o historial)
  GET  /api/mediciones   dashboard ← serie histórica para el gráfico
  GET  /api/salud        monitoreo ← API, base de datos y última llegada por sede
  WS   /ws               dashboard ← eventos {tipo: "estado" | "alerta", data}
Documentación interactiva (Swagger): /docs
"""
import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect, status
from fastapi.concurrency import run_in_threadpool
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from . import config, servicio
from .catalogo import PUNTOS
from .db import Alerta, Medicion, SesionLocal, crear_tablas, obtener_sesion
from .notificador import notificar
from .schemas import LoteEntrada, ResultadoIngesta, TokenEntrada, TokenSalida
from .seguridad import emitir_token, gateway_actual

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("induplac")


# ------------------------------------------------------------- WebSocket
class Difusor:
    """Mantiene los dashboards conectados y les envía cada evento."""

    def __init__(self):
        self.clientes: set[WebSocket] = set()

    async def conectar(self, ws: WebSocket):
        await ws.accept()
        self.clientes.add(ws)

    def desconectar(self, ws: WebSocket):
        self.clientes.discard(ws)

    async def enviar(self, evento: dict):
        for ws in list(self.clientes):
            try:
                await ws.send_json(evento)
            except Exception:
                self.desconectar(ws)


difusor = Difusor()


async def vigilar_sin_datos():
    """Cada segundo revisa qué sedes dejaron de enviar y avisa a los dashboards al cambiar."""
    anteriores: set[str] = set()
    while True:
        try:
            def revisar():
                with SesionLocal() as s:
                    actuales = servicio.sedes_sin_datos(s)
                    return actuales, (servicio.estado_actual(s, actuales) if actuales != anteriores else None)
            actuales, estado = await run_in_threadpool(revisar)
            if estado is not None:
                for sede in actuales - anteriores:
                    log.warning("Sede %s sin datos: el gateway dejó de enviar lotes", sede)
                await difusor.enviar({"tipo": "estado", "data": estado})
                anteriores = actuales
        except Exception:
            log.exception("Error vigilando sedes sin datos")
        await asyncio.sleep(1)


@asynccontextmanager
async def ciclo_vida(app: FastAPI):
    crear_tablas()
    tarea = asyncio.create_task(vigilar_sin_datos())
    yield
    tarea.cancel()


app = FastAPI(title="Induplac API", version="1.0.0", lifespan=ciclo_vida,
              description="Ingesta de mediciones IoT de las sedes Oficina RM y Planta Valparaíso.")


@app.middleware("http")
async def cabeceras_seguridad(request: Request, call_next):
    respuesta = await call_next(request)
    respuesta.headers["X-Content-Type-Options"] = "nosniff"   # hallazgo Z3 de ZAP
    respuesta.headers["X-Frame-Options"] = "DENY"
    respuesta.headers["Referrer-Policy"] = "same-origin"
    return respuesta


# --------------------------------------------------------------- ingesta
@app.post("/api/auth/token", response_model=TokenSalida, tags=["gateway"])
def token(datos: TokenEntrada):
    return TokenSalida(access_token=emitir_token(datos.gateway_id, datos.secreto), expira_en=config.JWT_MINUTOS * 60)


@app.post("/api/lotes", response_model=ResultadoIngesta, status_code=status.HTTP_201_CREATED, tags=["gateway"])
async def recibir_lotes(cuerpo: LoteEntrada | list[LoteEntrada], gw: dict = Depends(gateway_actual)):
    lotes = cuerpo if isinstance(cuerpo, list) else [cuerpo]
    if not lotes:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Lista de lotes vacía")
    if any(l.sede != gw["sede"] for l in lotes):
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"El gateway {gw['sub']} solo puede enviar datos de {gw['sede']}")

    def procesar():
        with SesionLocal() as s:
            return servicio.ingerir(s, lotes, gw["sub"])

    aceptados, descartados, eventos, nuevas = await run_in_threadpool(procesar)
    for evento in eventos:
        await difusor.enviar(evento)
    for alerta in nuevas:
        if alerta.nivel == "critico":
            asyncio.get_running_loop().run_in_executor(None, notificar, servicio.alerta_a_dict(alerta))
    log.info("%s: %d lote(s) aceptado(s), %d descartado(s)", gw["sub"], aceptados, descartados)
    return ResultadoIngesta(aceptados=aceptados, descartados=descartados)


# --------------------------------------------------------------- consulta
@app.get("/api/estado", tags=["dashboard"])
def get_estado(s: Session = Depends(obtener_sesion)):
    return servicio.estado_actual(s)


@app.get("/api/alertas", tags=["dashboard"])
def get_alertas(activas: bool | None = None, limite: int = Query(200, le=1000), s: Session = Depends(obtener_sesion)):
    q = select(Alerta).order_by(Alerta.ts.desc()).limit(limite)
    if activas is not None:
        q = q.where(Alerta.activa.is_(activas))
    return [servicio.alerta_a_dict(a) for a in s.scalars(q)]


@app.get("/api/mediciones", tags=["dashboard"])
def get_mediciones(sede: str | None = None, variable: str | None = None, desde: datetime | None = None,
                   limite: int = Query(2000, le=10000), s: Session = Depends(obtener_sesion)):
    if sede and sede not in PUNTOS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"sede desconocida: {sede}")
    q = select(Medicion)
    if sede:
        q = q.where(Medicion.sede == sede)
    if variable:
        q = q.where(Medicion.variable == variable)
    if desde:
        if desde.tzinfo:
            desde = desde.astimezone(timezone.utc).replace(tzinfo=None)
        q = q.where(Medicion.ts >= desde)
    # Las más recientes primero para respetar el límite, y luego en orden cronológico.
    filas = list(s.scalars(q.order_by(Medicion.ts.desc()).limit(limite)))[::-1]
    return [{"sede": m.sede, "variable": m.variable, "valor": m.valor, "unidad": m.unidad, "ts": servicio.iso(m.ts)}
            for m in filas]


@app.get("/api/salud", tags=["monitoreo"])
def salud(s: Session = Depends(obtener_sesion)):
    s.execute(text("SELECT 1"))
    recibidos = servicio.ultimo_recibido(s)
    sin_datos = servicio.sedes_sin_datos(s)
    return {"api": "ok", "base_datos": "ok", "version": app.version,
            "sedes": {sede: {"ultimo_lote_recibido": servicio.iso(recibidos[sede]) if sede in recibidos else None,
                             "sin_datos": sede in sin_datos} for sede in PUNTOS}}


@app.websocket("/ws")
async def ws(websocket: WebSocket):
    await difusor.conectar(websocket)
    try:
        while True:
            await websocket.receive_text()  # el dashboard no envía nada; solo mantiene la conexión
    except WebSocketDisconnect:
        difusor.desconectar(websocket)


# El dashboard se sirve desde la misma API (mismo origen: sin CORS).
# Se monta al final para no tapar /api/* ni /ws.
if os.path.isdir(config.FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=config.FRONTEND_DIR, html=True), name="frontend")
