"""Correos de aviso con un servidor SMTP simulado (no sale ningún correo real)."""
import time
from datetime import timedelta

import pytest

from app import config, notificador
from tests.conftest import token, token_usuario, usuario
from tests.test_api import T0, historial, lote


class SMTPFalso:
    enviados: list = []

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def starttls(self, **kwargs):
        pass

    def login(self, *args):
        pass

    def send_message(self, correo):
        SMTPFalso.enviados.append(correo)


@pytest.fixture()
def correos(monkeypatch):
    SMTPFalso.enviados = []
    monkeypatch.setattr(notificador.smtplib, "SMTP", SMTPFalso)
    monkeypatch.setattr(config, "SMTP_HOST", "smtp.prueba")
    monkeypatch.setattr(config, "SMTP_USER", "induplac@prueba.cl")
    monkeypatch.setattr(config, "ALERTA_DESTINO", "")  # vacío: se avisa a SMTP_USER
    return SMTPFalso.enviados


def esperar(correos, cantidad, segundos=3.0):
    """El envío corre en un executor: se espera un momento a que termine."""
    fin = time.monotonic() + segundos
    while len(correos) < cantidad and time.monotonic() < fin:
        time.sleep(0.05)
    time.sleep(0.2)  # margen para detectar correos de más
    return correos


def hora(desde, elec):
    """4 lotes de 15 min a partir de T0 + desde intervalos."""
    return [lote(ts=T0 + timedelta(minutes=15 * i), elec=elec) for i in range(desde, desde + 4)]


def test_alerta_critica_envia_un_correo_y_enfria(cliente, correos):
    h = token(cliente)
    cliente.post("/api/lotes", json=historial(horas=5, fin=T0 + timedelta(hours=4)), headers=h)
    cliente.post("/api/lotes", json=hora(1, 140 * 1.35), headers=h)  # pico: alerta crítica abierta
    assert len(esperar(correos, 1)) == 1
    assert correos[0]["Subject"] == "[Induplac] CRÍTICO · Planta Valparaíso · Electricidad"
    assert correos[0]["To"] == "induplac@prueba.cl"
    cliente.post("/api/lotes", json=hora(5, 140), headers=h)          # normaliza: se cierra
    cliente.post("/api/lotes", json=hora(9, 140 * 1.35), headers=h)   # nuevo pico dentro del enfriamiento
    assert len(cliente.get("/api/alertas", headers=usuario(cliente), params={"activas": True}).json()) == 1
    assert len(esperar(correos, 2)) == 1


def test_carga_de_historial_no_envia_correos(cliente, correos):
    # Un solo request (como el reenvío de la cola) donde la alerta se abre y se cierra.
    lotes = historial(horas=5, fin=T0 + timedelta(hours=4)) + hora(1, 140 * 1.35) + hora(5, 140)
    cliente.post("/api/lotes", json=lotes, headers=token(cliente))
    assert cliente.get("/api/alertas", headers=usuario(cliente), params={"activas": False}).json()  # la alerta existió
    assert esperar(correos, 1) == []


def test_sede_sin_datos_envia_correo(cliente, correos, monkeypatch):
    cliente.post("/api/lotes", json=lote(), headers=token(cliente))
    monkeypatch.setattr(config, "CICLO_SEG", 0)  # la tarea de vigilancia la detecta en ~1 s
    assert [c["Subject"] for c in esperar(correos, 1)] == ["[Induplac] SIN DATOS · Planta Valparaíso"]
