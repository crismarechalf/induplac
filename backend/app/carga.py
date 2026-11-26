"""Carga manual de lecturas por contingencia (gateway o medidor caído, corte largo de Internet).

El personal anota las lecturas en la plantilla y, cuando el sistema vuelve, un usuario
autorizado la sube en dos pasos: validar (no guarda nada) y confirmar.

- Mismo formato que la exportación de mediciones (exportar.py): un CSV exportado se puede
  volver a cargar. Acepta identificadores (oficina_rm, electricidad) o los nombres visibles
  que trae la exportación (Oficina RM, Electricidad).
- Cada fila pasa por las mismas reglas del gateway (schemas.error_medicion), más las propias:
  minutos del ciclo (00/15/30/45), no en el futuro ni con más de 90 días según el reloj de la
  plataforma, y permiso del rol sobre esa sede y variable (roles.puede_cargar).
"""
import csv
import io
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from . import roles, servicio
from .catalogo import NOMBRE_SEDE, NOMBRE_VARIABLE, PUNTOS
from .exportar import BOM, ENCABEZADOS, numero
from .schemas import error_medicion

ENCABEZADO = ENCABEZADOS["mediciones"]  # fecha_hora;sede;variable;valor;unidad
MAX_BYTES = 1_000_000
MAX_FILAS = 5_000
VIGENCIA_SEG = 15 * 60
MAX_ANTIGUEDAD = timedelta(days=90)
MAX_DETALLE = 200  # filas con error que se listan en el resumen

# Valores de ejemplo de la plantilla (consumo típico en turno por intervalo de 15 min).
EJEMPLO = {"electricidad": {"oficina_rm": 22.5, "planta": 140.2}, "agua": {"oficina_rm": 120, "planta": 900},
           "produccion": {"planta": 45}, "hh_sin_incidentes": {"oficina_rm": 18450, "planta": 96320},
           "uv": {"planta": 5.5}}

# Identificador o nombre visible → identificador.
_SEDES = {**{s: s for s in PUNTOS}, **{n.lower(): s for s, n in NOMBRE_SEDE.items()}}
_VARIABLES = {**{v: v for v in NOMBRE_VARIABLE}, **{n.lower(): v for v, n in NOMBRE_VARIABLE.items()}}


class ArchivoInvalido(Exception):
    """El archivo completo no se puede procesar (no una fila puntual)."""

    def __init__(self, status: int, mensaje: str):
        super().__init__(mensaje)
        self.status = status


def _local(ts: datetime) -> str:
    return servicio._local(ts).strftime("%Y-%m-%d %H:%M")


# ---------------------------------------------------------------- plantilla
def plantilla(sede: str, rol: str, hora_simulada: datetime) -> str:
    """CSV con el encabezado, instrucciones y una fila de ejemplo por variable que el rol puede cargar.

    Las instrucciones y los ejemplos empiezan con #: el importador los ignora.
    """
    buffer = io.StringIO()
    escritor = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    escritor.writerow(ENCABEZADO)
    buffer.write("# Plantilla de carga manual Induplac: las líneas que empiezan con # se ignoran.\r\n")
    buffer.write("# fecha_hora en hora de Chile (AAAA-MM-DD HH:MM) con minutos 00, 15, 30 o 45. "
                 "Decimales con coma. Una fila por variable y hora.\r\n")
    ejemplo = _local(servicio.piso_15min(hora_simulada))
    for variable, unidad in PUNTOS[sede].items():
        if roles.puede_cargar(rol, sede, variable):
            escritor.writerow([f"# {ejemplo}", sede, variable, numero(EJEMPLO[variable][sede]), unidad])
    return BOM + buffer.getvalue()


# ---------------------------------------------------------------- lectura y validación
def _decodificar(contenido: bytes) -> str:
    try:
        return contenido.decode("utf-8-sig")
    except UnicodeDecodeError:
        return contenido.decode("cp1252")  # "CSV (delimitado por comas)" de Excel en Windows


def _filas(texto: str) -> list[tuple[int, list[str]]]:
    """(número de línea, celdas) de las filas de datos, sin comentarios (#) ni líneas vacías."""
    lector = csv.reader(io.StringIO(texto), delimiter=";")
    filas, encabezado = [], None
    for celdas in lector:
        if not any(c.strip() for c in celdas) or celdas[0].lstrip().startswith("#"):
            continue
        if encabezado is None:
            encabezado = [c.strip().lower() for c in celdas]
            if encabezado != ENCABEZADO:
                pista = " (el separador debe ser punto y coma)" if len(celdas) == 1 and "," in celdas[0] else ""
                raise ArchivoInvalido(422, f"La primera fila debe ser {';'.join(ENCABEZADO)}{pista}.")
            continue
        filas.append((lector.line_num, celdas))
        if len(filas) > MAX_FILAS:
            raise ArchivoInvalido(422, f"El archivo supera las {MAX_FILAS:,} filas.".replace(",", "."))
    if encabezado is None:
        raise ArchivoInvalido(422, "El archivo está vacío.")
    return filas


def _valor(texto: str) -> float:
    texto = texto.strip().lstrip("'")
    if "," in texto:  # formato chileno: 1.234,5
        texto = texto.replace(".", "").replace(",", ".")
    return float(texto)


def _fila(celdas: list[str], rol: str, hora_simulada: datetime) -> dict | str:
    """La lectura validada, o el motivo por el que no sirve."""
    if len(celdas) != 5:
        return f"se esperaban 5 columnas y tiene {len(celdas)}"
    fecha, sede, variable, valor, unidad = (c.strip().lstrip("'").strip() for c in celdas)
    try:
        local = datetime.strptime(fecha, "%Y-%m-%d %H:%M")
    except ValueError:
        return f"fecha {fecha!r} con formato inválido (usa AAAA-MM-DD HH:MM)"
    if local.minute % 15:
        return f"los minutos deben ser 00, 15, 30 o 45 (tiene {local:%H:%M})"
    ts = local.replace(tzinfo=servicio.ZONA).astimezone(timezone.utc).replace(tzinfo=None)
    if ts > hora_simulada:
        return f"la fecha {fecha} está en el futuro (hora de la plataforma: {_local(hora_simulada)})"
    if ts < hora_simulada - MAX_ANTIGUEDAD:
        return f"la fecha {fecha} tiene más de 90 días de antigüedad"
    sede_id = _SEDES.get(sede.lower())
    if not sede_id:
        return f"sede desconocida: {sede!r} (usa oficina_rm o planta)"
    variable_id = _VARIABLES.get(variable.lower())
    if not variable_id:
        return f"variable desconocida: {variable!r}"
    try:
        numero_valor = _valor(valor)
    except ValueError:
        return f"valor {valor!r} no es un número"
    error = error_medicion(sede_id, variable_id, unidad, numero_valor)
    if error:
        return error
    if not roles.puede_cargar(rol, sede_id, variable_id):
        return f"tu perfil no puede cargar {NOMBRE_VARIABLE[variable_id]} de {NOMBRE_SEDE[sede_id]}"
    return {"sede": sede_id, "variable": variable_id, "valor": numero_valor, "unidad": unidad, "ts": ts}


def validar(s: Session, contenido: bytes, rol: str) -> dict:
    """Revisa el archivo sin guardar nada. Devuelve filas válidas, errores, duplicadas y rango."""
    if len(contenido) > MAX_BYTES:
        raise ArchivoInvalido(413, "El archivo supera 1 MB.")
    hora_simulada = servicio.hora_simulada(s)
    validas, errores, duplicadas = [], [], []
    vistas: dict[tuple, int] = {}
    for linea, celdas in _filas(_decodificar(contenido)):
        r = _fila(celdas, rol, hora_simulada)
        if isinstance(r, str):
            errores.append({"fila": linea, "motivo": r})
            continue
        clave = (r["sede"], r["variable"], r["ts"])
        if clave in vistas:
            errores.append({"fila": linea, "motivo": f"repetida en el archivo (igual a la fila {vistas[clave]})"})
            continue
        vistas[clave] = linea
        validas.append({**r, "fila": linea})
    # Duplicadas: ya existe una lectura guardada para esa sede, variable y hora.
    ya: dict[tuple, set] = {}
    nuevas = []
    for r in validas:
        clave = (r["sede"], r["ts"])
        if clave not in ya:
            ya[clave] = servicio.existentes(s, *clave)
        (duplicadas if r["variable"] in ya[clave] else nuevas).append(r)
    fechas = [r["ts"] for r in nuevas + duplicadas]
    return {
        "filas": nuevas,
        "resumen": {
            "filas_validas": len(nuevas),
            "filas_duplicadas": len(duplicadas),
            "filas_con_error": len(errores),
            "errores": errores[:MAX_DETALLE],
            "duplicadas": [r["fila"] for r in duplicadas][:MAX_DETALLE],
            "desde": _local(min(fechas)) if fechas else None,
            "hasta": _local(max(fechas)) if fechas else None,
            "sedes": sorted({r["sede"] for r in nuevas + duplicadas}),
        },
    }


# ---------------------------------------------------------------- cargas pendientes de confirmar
_pendientes: dict[str, dict] = {}
_candado = threading.Lock()


def reiniciar() -> None:
    with _candado:
        _pendientes.clear()


def guardar_pendiente(usuario: str, archivo: str, filas: list[dict], resumen: dict) -> str:
    """Guarda en memoria las filas validadas y devuelve el id_carga (vence en 15 minutos)."""
    id_carga = secrets.token_urlsafe(16)
    ahora = time.monotonic()
    with _candado:
        for clave in [k for k, p in _pendientes.items() if p["vence"] < ahora]:
            del _pendientes[clave]
        _pendientes[id_carga] = {"usuario": usuario, "archivo": archivo, "filas": filas,
                                 "resumen": resumen, "vence": ahora + VIGENCIA_SEG}
    return id_carga


def tomar_pendiente(id_carga: str, usuario: str) -> dict:
    """Saca la carga pendiente (se usa una sola vez). Lanza ArchivoInvalido si no sirve."""
    with _candado:
        p = _pendientes.get(id_carga)
        if p is None or p["vence"] < time.monotonic():
            _pendientes.pop(id_carga, None)
            raise ArchivoInvalido(404, "La carga no existe o venció (dura 15 minutos). Vuelve a subir el archivo.")
        if p["usuario"] != usuario:
            raise ArchivoInvalido(403, "Esa carga la validó otro usuario.")
        return _pendientes.pop(id_carga)
