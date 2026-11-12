"""Aviso por correo de alertas críticas (la jefatura se entera aunque no mire el dashboard).

Si no hay SMTP configurado, la alerta queda registrada en el log del contenedor.
"""
import logging
import smtplib
from email.message import EmailMessage

from . import config
from .catalogo import NOMBRE_SEDE, NOMBRE_VARIABLE

log = logging.getLogger("induplac.alertas")


def notificar(alerta: dict) -> None:
    asunto = (f"[Induplac] {alerta['nivel'].upper()} · {NOMBRE_SEDE[alerta['sede']]} · "
              f"{NOMBRE_VARIABLE[alerta['variable']]}")
    log.warning("%s — %s", asunto, alerta["mensaje"])
    if not (config.SMTP_HOST and config.ALERTA_DESTINO):
        return
    correo = EmailMessage()
    correo["Subject"] = asunto
    correo["From"] = config.SMTP_USER or "alertas@induplac.local"
    correo["To"] = config.ALERTA_DESTINO
    correo.set_content(f"{alerta['mensaje']}\n\nHora de la lectura (UTC): {alerta['ts']}")
    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=10) as smtp:
            smtp.starttls()
            if config.SMTP_USER:
                smtp.login(config.SMTP_USER, config.SMTP_PASS)
            smtp.send_message(correo)
    except Exception:  # un correo fallido no debe detener la ingesta
        log.exception("No se pudo enviar el correo de alerta")
