"""Login, bloqueo por intentos, tipos de token, filtrado por rol (REST y WebSocket) y auditoría."""
from datetime import timedelta

from fastapi.websockets import WebSocketDisconnect
import pytest

from tests.conftest import token, token_usuario, usuario
from tests.test_api import T0, lote

RM = ("gw-oficina-rm", "secreto-rm")


def login(cliente, nombre, clave):
    return cliente.post("/api/auth/login", json={"usuario": nombre, "clave": clave})


def test_login_correcto_e_incorrecto(cliente):
    r = login(cliente, "prevencion", "clave-usuarios")
    assert r.status_code == 200
    perfil = r.json()["usuario"]
    assert perfil["rol"] == "prevencion" and perfil["vista"] == {"oficina_rm": ["hh_sin_incidentes"],
                                                                 "planta": ["hh_sin_incidentes", "uv"]}
    assert "incidentes_registrar" in perfil["permisos"] and "consola" not in perfil["permisos"]
    assert login(cliente, "prevencion", "otra").status_code == 401
    assert login(cliente, "no_existe", "clave-usuarios").status_code == 401
    assert cliente.get("/api/yo", headers=usuario(cliente, "jefatura")).json()["rol"] == "jefatura"


def test_bloqueo_tras_5_intentos_fallidos(cliente):
    for _ in range(5):
        assert login(cliente, "jefatura", "mala").status_code == 401
    r = login(cliente, "jefatura", "clave-usuarios")  # incluso con la clave correcta
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0
    assert login(cliente, "admin", "clave-admin").status_code == 200  # el bloqueo es por usuario


def test_un_tipo_de_token_no_sirve_donde_va_el_otro(cliente):
    assert cliente.post("/api/lotes", json=lote(), headers=usuario(cliente)).status_code == 401
    assert cliente.get("/api/estado", headers=token(cliente)).status_code == 401
    assert cliente.get("/api/estado").status_code == 401
    assert cliente.get("/api/reloj", headers=token(cliente)).status_code == 200
    assert cliente.get("/api/reloj", headers=usuario(cliente)).status_code == 200


def test_filtrado_por_rol_en_estado_alertas_y_mediciones(cliente):
    cliente.post("/api/lotes", json=lote(uv=9), headers=token(cliente))  # alerta de UV en la Planta
    cliente.post("/api/lotes", json=lote(sede="oficina_rm"), headers=token(cliente, *RM))

    def ver(rol):
        h = usuario(cliente, rol)
        estado = {(e["sede"], e["variable"]) for e in cliente.get("/api/estado", headers=h).json()}
        alertas = cliente.get("/api/alertas", headers=h).json()
        serie = cliente.get("/api/mediciones", params={"sede": "planta", "variable": "uv"}, headers=h).json()
        return estado, alertas, serie

    estado, alertas, serie = ver("personal_rm")
    assert {s for s, _ in estado} == {"oficina_rm"} and alertas == [] and serie == []
    estado, alertas, serie = ver("prevencion")
    assert estado == {("oficina_rm", "hh_sin_incidentes"), ("planta", "hh_sin_incidentes"), ("planta", "uv")}
    assert [a["variable"] for a in alertas] == ["uv"] and len(serie) == 1
    estado, alertas, _ = ver("jefatura")
    assert len(estado) == 8 and len(alertas) == 1


def test_websocket_filtra_por_rol_y_exige_token(cliente):
    with pytest.raises(WebSocketDisconnect) as cierre:
        with cliente.websocket_connect("/ws?token=invalido") as ws:
            ws.receive_json()
    assert cierre.value.code == 4401
    with cliente.websocket_connect("/ws?token=" + token_usuario(cliente, "personal_rm")) as ws_rm, \
            cliente.websocket_connect("/ws?token=" + token_usuario(cliente, "personal_planta")) as ws_planta:
        cliente.post("/api/lotes", json=lote(uv=9), headers=token(cliente))           # Planta
        cliente.post("/api/lotes", json=lote(sede="oficina_rm"), headers=token(cliente, *RM))
        recibido = ws_rm.receive_json()  # lo primero que le llega a RM es su propio estado
        assert recibido["tipo"] == "estado" and {e["sede"] for e in recibido["data"]} == {"oficina_rm"}
        tipos_planta = {ws_planta.receive_json()["tipo"], ws_planta.receive_json()["tipo"]}
        assert tipos_planta == {"alerta", "estado"}


def test_auditoria_registra_login_y_consola(cliente):
    login(cliente, "jefatura", "mala")
    h = usuario(cliente)
    cliente.put("/api/simulacion/planta", json={"agua_pct": 30}, headers=h)
    registro = cliente.get("/api/auditoria", headers=h).json()
    assert [(a["usuario"], a["accion"]) for a in registro[:3]] == [
        ("admin", "consola"), ("admin", "login"), ("jefatura", "login_fallido")]
    assert all("clave" not in str(a["detalle"]) for a in registro)
    assert cliente.get("/api/auditoria", headers=usuario(cliente, "jefatura")).status_code == 403


def test_reloj_arranca_despues_del_ultimo_lote_existente(cliente):
    from app import servicio
    from app.db import Config, SesionLocal
    cliente.post("/api/lotes", json=lote(ts=T0 + timedelta(days=400)), headers=token(cliente))
    with SesionLocal() as s:  # simula una base que ya tenía datos antes de existir el reloj
        s.query(Config).delete()
        s.commit()
        servicio.iniciar_reloj(s)
        assert servicio.hora_simulada(s) >= (T0 + timedelta(days=400, minutes=15)).replace(tzinfo=None)
