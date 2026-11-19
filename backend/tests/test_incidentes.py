"""Registro de incidentes: permisos por rol, reinicio de HH en el gateway, correo y evento WebSocket."""
from datetime import datetime, timedelta, timezone

from tests.conftest import token, token_usuario, usuario
from tests.test_api import T0, lote
from tests.test_correos import correos, esperar  # noqa: F401  (fixture con SMTP simulado)

INCIDENTE = {"sede": "planta", "tipo": "Accidente con tiempo perdido",
             "descripcion": "Corte en la mano al manipular un tablero en la línea 2."}


def test_permisos_de_incidentes_por_rol(cliente):
    assert cliente.post("/api/incidentes", json=INCIDENTE, headers=usuario(cliente, "jefatura")).status_code == 403
    assert cliente.post("/api/incidentes", json=INCIDENTE, headers=usuario(cliente, "personal_planta")).status_code == 403
    assert cliente.get("/api/incidentes", headers=usuario(cliente, "personal_rm")).status_code == 403
    assert cliente.post("/api/incidentes", json=INCIDENTE).status_code == 401
    assert cliente.post("/api/incidentes", json={**INCIDENTE, "descripcion": "corto"},
                        headers=usuario(cliente, "prevencion")).status_code == 422
    futuro = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    assert cliente.post("/api/incidentes", json={**INCIDENTE, "ts": futuro},
                        headers=usuario(cliente, "prevencion")).status_code == 422


def test_incidente_reinicia_hh_avisa_por_correo_y_websocket(cliente, correos):  # noqa: F811
    cliente.post("/api/lotes", json=lote(), headers=token(cliente))
    with cliente.websocket_connect("/ws?token=" + token_usuario(cliente, "jefatura")) as ws:
        r = cliente.post("/api/incidentes", json=INCIDENTE, headers=usuario(cliente, "prevencion"))
        assert r.status_code == 201 and r.json()["registrado_por"] == "prevencion"
        evento = ws.receive_json()
    assert evento["tipo"] == "incidente" and evento["data"]["tipo"] == INCIDENTE["tipo"]
    # El gateway de la Planta ve un incidente_id nuevo (y pone sus HH en 0); la RM no.
    assert cliente.get("/api/simulacion/planta", headers=token(cliente)).json()["incidente_id"] == 1
    rm = token(cliente, "gw-oficina-rm", "secreto-rm")
    assert cliente.get("/api/simulacion/oficina_rm", headers=rm).json()["incidente_id"] == 0
    assert [c["Subject"] for c in esperar(correos, 1)] == [
        "[Induplac] INCIDENTE · Planta Valparaíso · Accidente con tiempo perdido"]
    assert "Registrado por: prevencion" in correos[0].get_content()
    recientes = cliente.get("/api/incidentes", headers=usuario(cliente, "jefatura")).json()
    assert len(recientes) == 1 and recientes[0]["sede"] == "planta"
    auditoria = cliente.get("/api/auditoria", headers=usuario(cliente)).json()
    assert ("prevencion", "incidente") in [(a["usuario"], a["accion"]) for a in auditoria]


def test_linea_detenida_abre_y_cierra_alerta(cliente):
    h = token(cliente)
    lunes = datetime(2026, 11, 16, 13, 0, tzinfo=timezone.utc)  # lunes 10:00 en Chile (turno)

    def con_produccion(i, valor):
        l = lote(ts=lunes + timedelta(minutes=15 * i))
        next(m for m in l["mediciones"] if m["variable"] == "produccion")["valor"] = valor
        return l

    cliente.post("/api/lotes", json=[con_produccion(0, 45), con_produccion(1, 0), con_produccion(2, 0)], headers=h)
    activas = cliente.get("/api/alertas", params={"activas": True}, headers=usuario(cliente)).json()
    assert [(a["variable"], a["nivel"]) for a in activas] == [("produccion", "advertencia")]
    assert activas[0]["mensaje"] == "Línea de producción detenida desde 10:15."
    cliente.post("/api/lotes", json=con_produccion(3, 40), headers=h)
    assert cliente.get("/api/alertas", params={"activas": True}, headers=usuario(cliente)).json() == []
