"""Avisos por correo cuando ocurre algo grave (la jefatura se entera aunque no mire el dashboard).

- Alerta crítica nueva que sigue activa al terminar el request que la generó.
- Sede que pasa a "sin datos" (gateway caído o enlace cortado).

Enfriamiento: como máximo 1 correo por (sede, variable) cada ALERTA_ENFRIAMIENTO_MIN minutos.
Sin SMTP configurado, el aviso queda solo en el log del contenedor.

Prueba manual del envío (dentro del contenedor):
    python -m app.notificador --prueba
"""
import logging
import smtplib
import ssl
import sys
import threading
import time
from datetime import datetime, timezone
from email.message import EmailMessage
from zoneinfo import ZoneInfo

from . import config
from .catalogo import NOMBRE_SEDE, NOMBRE_VARIABLE

log = logging.getLogger("induplac.alertas")
ZONA = ZoneInfo(config.ZONA)

_ultimo_envio: dict[tuple[str, str], float] = {}
_candado = threading.Lock()


def reiniciar() -> None:
    with _candado:
        _ultimo_envio.clear()


def _permitido(clave: tuple[str, str]) -> bool:
    """Reserva el envío si pasó el enfriamiento de esa (sede, variable)."""
    ahora = time.monotonic()
    with _candado:
        anterior = _ultimo_envio.get(clave)
        if anterior is not None and ahora - anterior < config.ALERTA_ENFRIAMIENTO_MIN * 60:
            return False
        _ultimo_envio[clave] = ahora
        return True


def destinatarios() -> list[str]:
    lista = [d.strip() for d in config.ALERTA_DESTINO.split(",") if d.strip()]
    return lista or ([config.SMTP_USER] if config.SMTP_USER else [])


def _hora_local(dt_utc: datetime) -> str:
    return dt_utc.replace(tzinfo=timezone.utc).astimezone(ZONA).strftime("%d-%m-%Y %H:%M")


def _pie() -> str:
    pie = f"Enviado: {datetime.now(ZONA):%d-%m-%Y %H:%M} (hora de Chile)"
    return pie + (f"\nDashboard: {config.URL_PUBLICA}" if config.URL_PUBLICA else "")


def aviso_alerta(alerta: dict) -> tuple[str, str] | None:
    """Asunto y cuerpo del correo de una alerta crítica, o None si está en enfriamiento."""
    if not _permitido((alerta["sede"], alerta["variable"])):
        return None
    asunto = f"[Induplac] CRÍTICO · {NOMBRE_SEDE[alerta['sede']]} · {NOMBRE_VARIABLE[alerta['variable']]}"
    lectura = _hora_local(datetime.fromisoformat(alerta["ts"].rstrip("Z")))
    cuerpo = (f"{alerta['mensaje']}\n\n"
              f"Hora de la lectura: {lectura} (en la demo es la hora simulada del gateway)\n{_pie()}")
    return asunto, cuerpo


def aviso_sin_datos(sede: str, ultimo_recibido: datetime | None) -> tuple[str, str] | None:
    if not _permitido((sede, "sin_datos")):
        return None
    asunto = f"[Induplac] SIN DATOS · {NOMBRE_SEDE[sede]}"
    ultimo = _hora_local(ultimo_recibido) if ultimo_recibido else "sin registro"
    cuerpo = (f"El gateway de {NOMBRE_SEDE[sede]} dejó de enviar lecturas "
              f"(gateway caído o enlace cortado).\n\nÚltimo lote recibido: {ultimo} (hora real de Chile)\n{_pie()}")
    return asunto, cuerpo


def _enviar_smtp(asunto: str, cuerpo: str) -> None:
    """Envía o lanza la excepción tal cual (la usa el comando --prueba)."""
    para = destinatarios()
    if not (config.SMTP_HOST and para):
        raise RuntimeError("SMTP no configurado: faltan SMTP_HOST o destinatario (ALERTA_DESTINO / SMTP_USER)")
    correo = EmailMessage()
    correo["Subject"] = asunto
    correo["From"] = config.SMTP_USER or "alertas@induplac.local"
    correo["To"] = ", ".join(para)
    correo.set_content(cuerpo)
    contexto = ssl.create_default_context()
    if config.SMTP_PORT == 465:
        servidor = smtplib.SMTP_SSL(config.SMTP_HOST, 465, timeout=15, context=contexto)
    else:
        servidor = smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=15)
    with servidor as smtp:
        if config.SMTP_PORT != 465:
            smtp.starttls(context=contexto)
        if config.SMTP_USER:
            smtp.login(config.SMTP_USER, config.SMTP_PASS)
        smtp.send_message(correo)


def enviar(asunto: str, cuerpo: str) -> None:
    """Corre en un executor: nunca debe romper ni bloquear la ingesta."""
    log.warning("%s — %s", asunto, cuerpo.splitlines()[0])
    if not config.SMTP_HOST:
        return
    try:
        _enviar_smtp(asunto, cuerpo)
    except Exception:
        log.exception("No se pudo enviar el correo de aviso")


if __name__ == "__main__":
    if "--prueba" not in sys.argv:
        sys.exit("Uso: python -m app.notificador --prueba")
    try:
        _enviar_smtp("[Induplac] Prueba de aviso", "Si lees esto, los avisos por correo de Induplac funcionan.\n\n" + _pie())
    except Exception as e:
        print(f"ERROR al enviar por {config.SMTP_HOST}:{config.SMTP_PORT}: {type(e).__name__}: {e}")
        sys.exit(1)
    print(f"OK: correo de prueba enviado a {', '.join(destinatarios())} por {config.SMTP_HOST}:{config.SMTP_PORT}")
