"""API REST + WebSocket de Induplac (FastAPI).

Endpoints:
  POST /api/auth/token         gateway → token JWT de gateway
  POST /api/auth/login         dashboard → token JWT de usuario (8 h) + perfil
  GET  /api/yo                 dashboard ← perfil del usuario del token
  POST /api/lotes              gateway → lote(s) de mediciones              [Bearer gateway]
  GET  /api/estado             dashboard ← último valor y estado (según rol)  [Bearer usuario]
  GET  /api/alertas            dashboard ← alertas (según rol)                [Bearer usuario]
  GET  /api/mediciones         dashboard ← serie para el gráfico (según rol)  [Bearer usuario]
  GET  /api/incidentes         dashboard ← incidentes recientes              [prevencion, jefatura, admin]
  POST /api/incidentes         dashboard → registra un incidente             [prevencion, admin]
  GET  /api/reloj              ambos ← hora simulada única                   [cualquier token]
  GET  /api/simulacion         consola ← estado de las dos sedes             [admin]
  PUT  /api/simulacion/{sede}  consola → ajusta las variables de una sede    [admin]
  POST /api/simulacion/restablecer  consola → todo en "Automático"          [admin]
  GET  /api/simulacion/{sede}  gateway ← lo que debe aplicar en su ciclo     [Bearer gateway de esa sede]
  GET  /api/auditoria          admin ← quién hizo qué y cuándo               [admin]
  GET  /api/exportar/{recurso} dashboard ← CSV de mediciones, alertas, incidentes o auditoría (según rol)
  GET  /api/carga-manual/plantilla   contingencia ← plantilla CSV de una sede      [admin, jefatura, prevencion]
  POST /api/carga-manual/validar     contingencia → revisa el CSV sin guardar      [admin, jefatura, prevencion]
  POST /api/carga-manual/confirmar   contingencia → guarda lo validado             [admin, jefatura, prevencion]
  GET  /api/salud              monitoreo ← API, base y última llegada por sede (público, sin datos de negocio)
  WS   /ws?token=            dashboard ← eventos estado | alerta | incidente (según rol; sin token → 4401)
Documentación interactiva (Swagger): /docs
"""
import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import (Depends, FastAPI, File, HTTPException, Query, Request, Response, UploadFile, WebSocket,
                     WebSocketDisconnect, status)
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from . import carga, config, exportar, notificador, roles, seguridad, servicio, simulacion
from .catalogo import NOMBRE_SEDE, NOMBRE_VARIABLE, PUNTOS
from .db import Incidente, SesionLocal, Usuario, crear_tablas, obtener_sesion
from .schemas import LoteEntrada, ResultadoIngesta, TokenEntrada, TokenSalida
from .seguridad import cualquier_token, gateway_actual, requiere, usuario_actual
from .usuarios import sembrar

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("induplac")


# ------------------------------------------------------------- WebSocket
def filtrar_evento(evento: dict, rol: str) -> dict | None:
    """Solo lo que el rol puede ver (None = no se envía)."""
    tipo, data = evento["tipo"], evento["data"]
    if tipo == "estado":
        visibles = [e for e in data if roles.puede_ver(rol, e["sede"], e["variable"])]
        return {"tipo": tipo, "data": visibles} if visibles else None
    if tipo == "alerta":
        return evento if roles.puede_ver(rol, data["sede"], data["variable"]) else None
    if tipo == "incidente":
        return evento if roles.tiene_permiso(rol, "incidentes_ver") else None
    return None


class Difusor:
    """Mantiene los dashboards conectados (con su rol) y les envía cada evento filtrado."""

    def __init__(self):
        self.clientes: dict[WebSocket, str] = {}

    def desconectar(self, ws: WebSocket):
        self.clientes.pop(ws, None)

    async def enviar(self, evento: dict):
        for ws, rol in list(self.clientes.items()):
            filtrado = filtrar_evento(evento, rol)
            if filtrado is None:
                continue
            try:
                await ws.send_json(filtrado)
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
    crear_tablas()  # crea solo las tablas que falten: no toca los datos existentes
    with SesionLocal() as s:
        sembrar(s)
        servicio.iniciar_reloj(s)
    tareas = [asyncio.create_task(vigilar_sin_datos()), asyncio.create_task(podar_periodicamente())]
    yield
    for tarea in tareas:
        tarea.cancel()


app = FastAPI(title="Induplac API", version="2.0.0", lifespan=ciclo_vida,
              description="Ingesta de mediciones IoT de las sedes Oficina RM y Planta Valparaíso.")


@app.middleware("http")
async def cabeceras_seguridad(request: Request, call_next):
    respuesta = await call_next(request)
    respuesta.headers["X-Content-Type-Options"] = "nosniff"   # hallazgo Z3 de ZAP
    respuesta.headers["X-Frame-Options"] = "DENY"
    respuesta.headers["Referrer-Policy"] = "same-origin"
    return respuesta


# --------------------------------------------------------------- autenticación
class LoginEntrada(BaseModel):
    usuario: str = Field(min_length=1, max_length=40)
    clave: str = Field(min_length=1, max_length=200)


def perfil(u: Usuario | dict) -> dict:
    """Lo que el dashboard necesita para armar la pantalla del usuario."""
    datos = {"usuario": u.usuario, "nombre": u.nombre, "rol": u.rol, "sede": u.sede} if isinstance(u, Usuario) else u
    rol = roles.ROLES[datos["rol"]]
    return {**datos, "rol_nombre": rol["nombre"], "vista": rol["vista"], "permisos": sorted(rol["permisos"])}


@app.post("/api/auth/token", response_model=TokenSalida, tags=["gateway"])
def token(datos: TokenEntrada):
    return TokenSalida(access_token=seguridad.emitir_token(datos.gateway_id, datos.secreto),
                       expira_en=config.JWT_MINUTOS * 60)


@app.post("/api/auth/login", tags=["usuarios"])
def login(datos: LoginEntrada, s: Session = Depends(obtener_sesion)):
    espera = seguridad.bloqueado(datos.usuario)
    if espera:
        servicio.auditar(s, datos.usuario, "login_bloqueado")
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            f"Demasiados intentos fallidos. Intenta de nuevo en {espera // 60 + 1} minuto(s).",
                            headers={"Retry-After": str(espera)})
    u = s.scalar(select(Usuario).where(Usuario.usuario == datos.usuario))
    if not (seguridad.comprobar_clave(datos.clave, u.hash if u else None) and u.activo):
        seguridad.registrar_fallo(datos.usuario)
        servicio.auditar(s, datos.usuario, "login_fallido")  # nunca se guarda la clave
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Usuario o contraseña incorrectos")
    seguridad.limpiar_fallos(datos.usuario)
    servicio.auditar(s, u.usuario, "login")
    return {"access_token": seguridad.emitir_token_usuario(u.usuario, u.rol, u.sede), "token_type": "bearer",
            "expira_en": config.SESION_HORAS * 3600, "usuario": perfil(u)}


@app.get("/api/yo", tags=["usuarios"])
def yo(u: dict = Depends(usuario_actual), s: Session = Depends(obtener_sesion)):
    fila = s.scalar(select(Usuario).where(Usuario.usuario == u["sub"], Usuario.activo.is_(True)))
    if not fila:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Usuario desactivado")
    return perfil(fila)


# --------------------------------------------------------------- ingesta
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


# --------------------------------------------------------------- consulta (filtrada por rol)
@app.get("/api/estado", tags=["dashboard"])
def get_estado(u: dict = Depends(usuario_actual), s: Session = Depends(obtener_sesion)):
    return servicio.estado_actual(s, vista=roles.vista(u["rol"]))


@app.get("/api/alertas", tags=["dashboard"])
def get_alertas(activas: bool | None = None, limite: int = Query(200, ge=1, le=1000),
                u: dict = Depends(usuario_actual), s: Session = Depends(obtener_sesion)):
    return servicio.alertas(s, roles.vista(u["rol"]), activas, limite)


@app.get("/api/mediciones", tags=["dashboard"])
def get_mediciones(sede: str | None = None, variable: str | None = None, desde: datetime | None = None,
                   limite: int = Query(2000, ge=1, le=10000),
                   u: dict = Depends(usuario_actual), s: Session = Depends(obtener_sesion)):
    if sede and sede not in PUNTOS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"sede desconocida: {sede}")
    if desde and desde.tzinfo:
        desde = desde.astimezone(timezone.utc).replace(tzinfo=None)
    return servicio.mediciones(s, roles.vista(u["rol"]), sede, variable, desde, limite)


@app.get("/api/salud", tags=["monitoreo"])
def salud(s: Session = Depends(obtener_sesion)):
    s.execute(text("SELECT 1"))
    recibidos = servicio.ultimo_recibido(s)
    sin_datos = servicio.sedes_sin_datos(s)
    return {"api": "ok", "base_datos": "ok", "version": app.version,
            "sedes": {sede: {"ultimo_lote_recibido": servicio.iso(recibidos[sede]) if sede in recibidos else None,
                             "sin_datos": sede in sin_datos} for sede in PUNTOS}}


@app.get("/api/reloj", tags=["dashboard", "gateway"])
def reloj(_: dict = Depends(cualquier_token), s: Session = Depends(obtener_sesion)):
    return {"hora_simulada": servicio.iso(servicio.hora_simulada(s)), "factor": servicio.factor_reloj()}


# --------------------------------------------------------------- incidentes
class IncidenteEntrada(BaseModel):
    sede: Literal[tuple(PUNTOS)]
    ts: datetime | None = Field(None, description="Cuándo ocurrió (ISO 8601 con zona). Por defecto, ahora")
    tipo: Literal[servicio.TIPOS_INCIDENTE]
    descripcion: str = Field(min_length=10, max_length=500)

    @field_validator("descripcion")
    @classmethod
    def sin_espacios_de_mas(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 10:
            raise ValueError("la descripción debe tener al menos 10 caracteres")
        return v

    @field_validator("ts")
    @classmethod
    def a_utc(cls, v: datetime | None) -> datetime | None:
        if v is None:
            return v
        if v.tzinfo is None:
            raise ValueError("ts debe incluir zona horaria")
        v = v.astimezone(timezone.utc).replace(tzinfo=None)
        if v > servicio.ahora_utc() + timedelta(minutes=5):
            raise ValueError("la fecha del incidente no puede estar en el futuro")
        return v


@app.get("/api/incidentes", tags=["incidentes"])
def get_incidentes(limite: int = Query(5, ge=1, le=200), _: dict = Depends(requiere("incidentes_ver")),
                   s: Session = Depends(obtener_sesion)):
    return servicio.incidentes(s, limite)


@app.post("/api/incidentes", status_code=status.HTTP_201_CREATED, tags=["incidentes"])
async def post_incidente(datos: IncidenteEntrada, u: dict = Depends(requiere("incidentes_registrar"))):
    def guardar():
        with SesionLocal() as s:
            ahora = servicio.ahora_utc()
            i = Incidente(sede=datos.sede, ts=datos.ts or ahora, tipo=datos.tipo, descripcion=datos.descripcion,
                          registrado_por=u["sub"], creado=ahora)
            s.add(i)
            s.commit()
            d = servicio.incidente_a_dict(i)
            servicio.auditar(s, u["sub"], "incidente", {"id": d["id"], "sede": d["sede"], "tipo": d["tipo"]})
            return d

    incidente = await run_in_threadpool(guardar)
    await difusor.enviar({"tipo": "incidente", "data": incidente})
    avisar(notificador.aviso_incidente(incidente))
    log.warning("Incidente en %s (%s) registrado por %s", incidente["sede"], incidente["tipo"], u["sub"])
    return incidente


# --------------------------------------------------------------- consola de operación (admin)
class CambiosSimulacion(BaseModel):
    """Solo los campos enviados se cambian. uv_forzado: null = automático."""
    model_config = ConfigDict(extra="forbid")
    electricidad_pct: int | None = Field(None, ge=-50, le=100)
    agua_pct: int | None = Field(None, ge=-50, le=100)
    produccion_pct: int | None = Field(None, ge=0, le=150)
    uv_forzado: float | None = Field(None, ge=0, le=14)
    enlace_cortado: bool | None = None


def estado_consola(s: Session) -> dict:
    return {
        "sedes": simulacion.todas(),
        "controles": {sede: simulacion.controles(sede) for sede in PUNTOS},
        "hora_simulada": servicio.iso(servicio.hora_simulada(s)),
        "factor": servicio.factor_reloj(),
        "registro": servicio.auditoria(s, 10, ("consola", "restablecer")),
    }


@app.get("/api/simulacion", tags=["consola"])
def get_simulacion(_: dict = Depends(requiere("consola")), s: Session = Depends(obtener_sesion)):
    return estado_consola(s)


@app.post("/api/simulacion/restablecer", tags=["consola"])
def post_restablecer(u: dict = Depends(requiere("consola")), s: Session = Depends(obtener_sesion)):
    simulacion.restablecer()
    servicio.auditar(s, u["sub"], "restablecer")
    log.info("Consola: %s restableció la simulación", u["sub"])
    return estado_consola(s)


@app.put("/api/simulacion/{sede}", tags=["consola"])
def put_simulacion(sede: str, datos: CambiosSimulacion, u: dict = Depends(requiere("consola")),
                   s: Session = Depends(obtener_sesion)):
    if sede not in PUNTOS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"sede desconocida: {sede}")
    cambios = {campo: getattr(datos, campo) for campo in datos.model_fields_set}
    if not cambios:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "No se indicó ningún cambio")
    for campo, valor in cambios.items():
        if campo not in simulacion.controles(sede):
            variable = NOMBRE_VARIABLE[simulacion.VARIABLE_DEL_CONTROL[campo]]
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                f"{NOMBRE_SEDE[sede]} no mide {variable}: {campo} no aplica")
        if valor is None and campo != "uv_forzado":
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"{campo} no puede ser null")
    simulacion.aplicar(sede, cambios)
    servicio.auditar(s, u["sub"], "consola", {"sede": sede, **cambios})
    log.info("Consola: %s cambió %s %s", u["sub"], sede, cambios)
    return estado_consola(s)


@app.get("/api/simulacion/{sede}", tags=["gateway"])
def get_simulacion_sede(sede: str, gw: dict = Depends(gateway_actual), s: Session = Depends(obtener_sesion)):
    if sede not in PUNTOS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"sede desconocida: {sede}")
    if sede != gw["sede"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"El gateway {gw['sub']} solo puede consultar {gw['sede']}")
    # incidente_id = incidentes registrados en la sede: si sube, el gateway reinicia sus HH.
    return {**simulacion.BASE, **simulacion.de_sede(sede), "incidente_id": servicio.conteo_incidentes(s, sede)}


@app.get("/api/auditoria", tags=["consola"])
def get_auditoria(limite: int = Query(50, ge=1, le=500), _: dict = Depends(requiere("auditoria")),
                  s: Session = Depends(obtener_sesion)):
    return servicio.auditoria(s, limite)


# --------------------------------------------------------------- exportación CSV
_ERRORES_EXPORTAR = {
    401: {"description": "Sin token o con token de gateway (solo se aceptan tokens de usuario)"},
    403: {"description": "El rol no tiene acceso al recurso, o pidió una sede o variable fuera de su permiso"},
    422: {"description": "Falta el período, desde > hasta, período de más de 90 días o variable que no existe en la sede"},
}


@app.get("/api/exportar/{recurso}", tags=["exportación"], response_class=StreamingResponse,
         summary="Exportar a CSV lo que el usuario puede ver",
         responses={200: {"content": {"text/csv": {}},
                          "description": "CSV para Excel (UTF-8 con BOM, separador ;, decimales con coma, hora de Chile)"},
                    **_ERRORES_EXPORTAR})
def get_exportar(
    recurso: Literal[exportar.RECURSOS],
    desde: datetime | None = Query(None, description="Inicio del período, ISO 8601 con zona (ej. 2026-11-18T00:00:00-03:00)"),
    hasta: datetime | None = Query(None, description="Fin del período, ISO 8601 con zona. Máximo 90 días después de desde"),
    sede: str | None = Query(None, description="oficina_rm o planta (opcional; no aplica a auditoría)"),
    variable: str | None = Query(None, description="Solo para mediciones y alertas (opcional)"),
    u: dict = Depends(usuario_actual),
    s: Session = Depends(obtener_sesion),
):
    def rechazar(codigo: int, mensaje: str):
        raise HTTPException(codigo, mensaje)

    rol, vista = u["rol"], roles.vista(u["rol"])
    permiso = exportar.PERMISO[recurso]
    if permiso and not roles.tiene_permiso(rol, permiso):
        rechazar(403, f"Tu perfil no puede exportar {recurso}.")
    if desde is None or hasta is None:
        rechazar(422, "Indica el período a exportar (desde y hasta).")
    if desde.tzinfo is None or hasta.tzinfo is None:
        rechazar(422, "Las fechas deben incluir la zona horaria.")
    desde = desde.astimezone(timezone.utc).replace(tzinfo=None)
    hasta = hasta.astimezone(timezone.utc).replace(tzinfo=None)
    if desde > hasta:
        rechazar(422, "La fecha de inicio es posterior a la de término.")
    if hasta - desde > timedelta(days=90):
        rechazar(422, "El período no puede superar los 90 días.")
    if sede and sede not in PUNTOS:
        rechazar(422, f"La sede {sede} no existe.")
    if sede and recurso not in exportar.CON_SEDE:
        rechazar(422, "La auditoría no se filtra por sede.")
    if variable and recurso not in exportar.CON_VARIABLE:
        rechazar(422, "El filtro por variable solo aplica a mediciones y alertas.")
    if recurso in exportar.CON_VARIABLE:
        if sede and sede not in vista:
            rechazar(403, f"Tu perfil no puede ver datos de {NOMBRE_SEDE[sede]}.")
        if variable:
            sedes = [sede] if sede else list(PUNTOS)
            if not any(variable in PUNTOS[x] for x in sedes):
                rechazar(422, f"{' ni '.join(NOMBRE_SEDE[x] for x in sedes)} no mide {variable}.")
            if not any(variable in vista.get(x, ()) for x in sedes):
                rechazar(403, f"Tu perfil no puede ver {NOMBRE_VARIABLE[variable]}.")

    q = exportar.consulta(recurso, vista, desde, hasta, sede, variable)
    filas = exportar.contar(s, q)
    servicio.auditar(s, u["sub"], "exportacion", {
        "recurso": recurso, "desde": servicio.iso(desde), "hasta": servicio.iso(hasta),
        "sede": sede or "todas", "variable": variable, "filas": filas})
    nombre = (f"induplac_{recurso}_{sede or 'todas'}_"
              f"{servicio._local(desde):%Y-%m-%d}_{servicio._local(hasta):%Y-%m-%d}.csv")
    return StreamingResponse(exportar.generar_csv(SesionLocal, recurso, q), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{nombre}"'})


# --------------------------------------------------------------- carga manual (contingencia)
class ErrorFila(BaseModel):
    fila: int = Field(description="Número de línea en el archivo")
    motivo: str


class ResumenCarga(BaseModel):
    id_carga: str = Field(description="Para confirmar; vence en 15 minutos")
    vence_en_seg: int
    archivo: str
    filas_validas: int = Field(description="Se guardarán al confirmar")
    filas_duplicadas: int = Field(description="Ya existen para esa sede, variable y hora")
    filas_con_error: int
    errores: list[ErrorFila] = Field(description="Hasta 200 filas con su motivo")
    duplicadas: list[int] = Field(description="Números de línea de las filas duplicadas (hasta 200)")
    desde: str | None = Field(description="Primera fecha del archivo, hora de Chile")
    hasta: str | None
    sedes: list[str]


class ConfirmarCarga(BaseModel):
    id_carga: str


class ResultadoCarga(BaseModel):
    guardadas: int
    descartadas: int = Field(description="Filas con error o duplicadas")


_ERRORES_CARGA = {
    401: {"description": "Sin token o con token de gateway"},
    403: {"description": "El rol no puede hacer cargas manuales (o la carga la validó otro usuario)"},
}


@app.get("/api/carga-manual/plantilla", tags=["carga manual"], response_class=Response,
         summary="Plantilla CSV para anotar lecturas a mano",
         responses={200: {"content": {"text/csv": {}}, "description": "Encabezado + filas de ejemplo con # (se ignoran)"},
                    **_ERRORES_CARGA, 422: {"description": "Sede inexistente"}})
def get_plantilla(sede: str = Query(..., description="oficina_rm o planta"),
                  u: dict = Depends(requiere("carga_manual")), s: Session = Depends(obtener_sesion)):
    if sede not in PUNTOS:
        raise HTTPException(422, f"La sede {sede} no existe (usa oficina_rm o planta).")
    contenido = carga.plantilla(sede, u["rol"], servicio.hora_simulada(s))
    return Response(contenido, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="induplac_plantilla_carga_{sede}.csv"'})


@app.post("/api/carga-manual/validar", tags=["carga manual"], response_model=ResumenCarga,
          summary="Revisar un CSV de carga manual (no guarda nada)",
          responses={**_ERRORES_CARGA, 413: {"description": "Archivo de más de 1 MB"},
                     422: {"description": "Encabezado incorrecto, archivo vacío o más de 5.000 filas"}})
async def post_validar(archivo: UploadFile = File(..., description="CSV con el formato de la plantilla"),
                       u: dict = Depends(requiere("carga_manual"))):
    contenido = await archivo.read(carga.MAX_BYTES + 1)

    def revisar():
        with SesionLocal() as s:
            r = carga.validar(s, contenido, u["rol"])
            servicio.auditar(s, u["sub"], "carga_validacion", {"archivo": archivo.filename, **{
                k: r["resumen"][k] for k in ("sedes", "desde", "hasta", "filas_validas", "filas_duplicadas",
                                              "filas_con_error")}})
            return r
    try:
        r = await run_in_threadpool(revisar)
    except carga.ArchivoInvalido as e:
        raise HTTPException(e.status, str(e))
    id_carga = carga.guardar_pendiente(u["sub"], archivo.filename or "archivo.csv", r["filas"], r["resumen"])
    return {"id_carga": id_carga, "vence_en_seg": carga.VIGENCIA_SEG, "archivo": archivo.filename or "", **r["resumen"]}


@app.post("/api/carga-manual/confirmar", tags=["carga manual"], response_model=ResultadoCarga,
          summary="Guardar las filas válidas y no duplicadas de una carga validada",
          responses={**_ERRORES_CARGA, 404: {"description": "id_carga inexistente o vencido"}})
async def post_confirmar(datos: ConfirmarCarga, u: dict = Depends(requiere("carga_manual"))):
    try:
        pendiente = carga.tomar_pendiente(datos.id_carga, u["sub"])
    except carga.ArchivoInvalido as e:
        raise HTTPException(e.status, str(e))
    resumen = pendiente["resumen"]

    def guardar():
        with SesionLocal() as s:
            guardadas, duplicadas, eventos = servicio.ingerir_manual(s, pendiente["filas"], u["sub"])
            descartadas = resumen["filas_con_error"] + resumen["filas_duplicadas"] + duplicadas
            servicio.auditar(s, u["sub"], "carga_confirmacion", {
                "archivo": pendiente["archivo"], "sedes": resumen["sedes"], "desde": resumen["desde"],
                "hasta": resumen["hasta"], "guardadas": guardadas, "descartadas": descartadas})
            return guardadas, descartadas, eventos, servicio.estado_actual(s)

    guardadas, descartadas, eventos, estado = await run_in_threadpool(guardar)
    for evento in eventos:  # alertas solo de lecturas más nuevas que las guardadas; sin correos
        await difusor.enviar(evento)
    await difusor.enviar({"tipo": "estado", "data": estado})  # el dashboard se refresca
    log.info("Carga manual de %s: %d guardadas, %d descartadas", u["sub"], guardadas, descartadas)
    return {"guardadas": guardadas, "descartadas": descartadas}


# --------------------------------------------------------------- WebSocket
@app.websocket("/ws")
async def ws(websocket: WebSocket, token: str = ""):
    await websocket.accept()
    try:
        rol = seguridad.decodificar(token, "usuario")["rol"]
    except HTTPException:
        # 4401: el dashboard vuelve a la pantalla de login.
        await websocket.close(code=4401, reason="Token inválido o vencido")
        return
    difusor.clientes[websocket] = rol
    try:
        while True:
            await websocket.receive_text()  # el dashboard no envía nada; solo mantiene la conexión
    except WebSocketDisconnect:
        difusor.desconectar(websocket)


# El dashboard se sirve desde la misma API (mismo origen: sin CORS).
# Se monta al final para no tapar /api/* ni /ws.
if os.path.isdir(config.FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=config.FRONTEND_DIR, html=True), name="frontend")
