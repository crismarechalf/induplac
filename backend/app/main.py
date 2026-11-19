"""API REST + WebSocket de Induplac (FastAPI).

Endpoints:
  POST /api/auth/token   gateway → token JWT
  POST /api/lotes        gateway → lote(s) de mediciones           [requiere Bearer]
  GET  /api/estado       dashboard ← último valor y estado de cada punto
  GET  /api/alertas      dashboard ← alertas (activas o historial)
  GET  /api/mediciones   dashboard ← serie histórica para el gráfico
  GET  /api/salud        monitoreo ← API, base de datos y última llegada por sede
  GET  /api/simulacion   dashboard ← escenarios de demo activos
  POST /api/simulacion   dashboard → aplica un escenario                [requiere usuario/contraseña de demo]
  GET  /api/simulacion/{sede}  gateway ← escenarios que debe aplicar   [requiere Bearer de esa sede]
  WS   /ws               dashboard ← eventos {tipo: "estado" | "alerta", data}
Documentación interactiva (Swagger): /docs
"""
import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect, status
from fastapi.concurrency import run_in_threadpool
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from . import config, notificador, servicio, simulacion
from .catalogo import PUNTOS
from .db import Alerta, Medicion, SesionLocal, crear_tablas, obtener_sesion
from .schemas import LoteEntrada, ResultadoIngesta, TokenEntrada, TokenSalida
from .seguridad import emitir_token, gateway_actual, operador_demo

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


def avisar(aviso: tuple[str, str] | None) -> None:
    """Envía el correo en un executor: la ingesta nunca espera al SMTP."""
    if aviso:
        asyncio.get_running_loop().run_in_executor(None, notificador.enviar, *aviso)


async def vigilar_sin_datos():
    """Cada segundo revisa qué sedes dejaron de enviar; al cambiar avisa a los dashboards y por correo."""
    anteriores: set[str] = set()
    while True:
        try:
            def revisar():
                with SesionLocal() as s:
                    actuales = servicio.sedes_sin_datos(s)
                    if actuales == anteriores:
                        return actuales, None, {}
                    return actuales, servicio.estado_actual(s, actuales), servicio.ultimo_recibido(s)
            actuales, estado, recibidos = await run_in_threadpool(revisar)
            if estado is not None:
                for sede in actuales - anteriores:
                    log.warning("Sede %s sin datos: el gateway dejó de enviar lotes", sede)
                    avisar(notificador.aviso_sin_datos(sede, recibidos.get(sede)))
                await difusor.enviar({"tipo": "estado", "data": estado})
                anteriores = actuales
        except Exception:
            log.exception("Error vigilando sedes sin datos")
        await asyncio.sleep(1)


async def podar_periodicamente():
    """Al arrancar y cada hora borra las mediciones viejas (RETENCION_DIAS).

    Con ciclos de 3 s, 1 hora real son ~12 días simulados: por eso cada hora y no una vez al día.
    """
    while True:
        try:
            def podar():
                with SesionLocal() as s:
                    return servicio.podar(s)
            borradas = await run_in_threadpool(podar)
            if borradas:
                log.info("Retención: %d mediciones de más de %d días borradas", borradas, config.RETENCION_DIAS)
        except Exception:
            log.exception("Error en la retención de mediciones")
        await asyncio.sleep(3600)


@asynccontextmanager
async def ciclo_vida(app: FastAPI):
    crear_tablas()
    tareas = [asyncio.create_task(vigilar_sin_datos()), asyncio.create_task(podar_periodicamente())]
    yield
    for tarea in tareas:
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
    # Correo solo si la alerta crítica sigue activa al terminar el request: así no salen avisos
    # por la carga del historial ni por alertas que se abren y cierran dentro del mismo reenvío.
    for alerta in nuevas:
        if alerta.nivel == "critico" and alerta.activa:
            avisar(notificador.aviso_alerta(servicio.alerta_a_dict(alerta)))
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


# --------------------------------------------------------------- simulación (panel "Demo")
class AccionSimulacion(BaseModel):
    accion: Literal[simulacion.ACCIONES]
    sede: Literal[tuple(PUNTOS)] | None = None


@app.get("/api/simulacion", tags=["demo"])
def get_simulacion():
    return simulacion.resumen()


@app.post("/api/simulacion", tags=["demo"], dependencies=[Depends(operador_demo)])
def post_simulacion(datos: AccionSimulacion):
    if datos.accion in simulacion.ACCIONES_CON_SEDE and not datos.sede:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"La acción {datos.accion} requiere la sede")
    log.info("Demo: %s %s", datos.accion, datos.sede or "")
    return simulacion.aplicar(datos.accion, datos.sede)


@app.get("/api/simulacion/{sede}", tags=["demo"])
def get_simulacion_sede(sede: str, gw: dict = Depends(gateway_actual)):
    if sede not in PUNTOS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"sede desconocida: {sede}")
    if sede != gw["sede"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"El gateway {gw['sub']} solo puede consultar {gw['sede']}")
    return simulacion.para_sede(sede)


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
