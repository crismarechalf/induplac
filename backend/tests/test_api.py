"""Pruebas de integración de la API REST (cliente → API → backend → base de datos)."""
from datetime import datetime, timedelta, timezone

from app import config
from tests.conftest import token

T0 = datetime(2026, 11, 18, 18, 0, tzinfo=timezone.utc)  # miércoles 15:00 en Chile


def lote(sede="planta", ts=T0, elec=140.0, agua=900, uv=5.0):
    med = [{"variable": "electricidad", "valor": elec, "unidad": "kWh"},
           {"variable": "agua", "valor": agua, "unidad": "L"},
           {"variable": "hh_sin_incidentes", "valor": 1000, "unidad": "h"}]
    if sede == "planta":
        med += [{"variable": "produccion", "valor": 45, "unidad": "tableros"},
                {"variable": "uv", "valor": uv, "unidad": "índice"}]
    return {"sede": sede, "ts": ts.isoformat().replace("+00:00", "Z"), "mediciones": med}


def historial(semanas=4, horas=2, fin=T0):
    """Lotes cada 15 min de las mismas horas en las semanas previas + la hora actual."""
    lotes = []
    for k in range(semanas, 0, -1):
        base = fin - timedelta(weeks=k)
        lotes += [lote(ts=base - timedelta(minutes=15 * i)) for i in range(4 * horas - 1, -1, -1)]
    return lotes


# ---------------------------------------------------------------- seguridad
def test_sin_token_rechaza(cliente):
    assert cliente.post("/api/lotes", json=lote()).status_code == 401


def test_secreto_incorrecto(cliente):
    r = cliente.post("/api/auth/token", json={"gateway_id": "gw-planta", "secreto": "x"})
    assert r.status_code == 401


def test_gateway_no_puede_suplantar_otra_sede(cliente):
    r = cliente.post("/api/lotes", json=lote(sede="oficina_rm"), headers=token(cliente))
    assert r.status_code == 403


def test_cabecera_nosniff(cliente):
    assert cliente.get("/api/estado").headers["x-content-type-options"] == "nosniff"


# ---------------------------------------------------------------- validación
def test_unidad_incorrecta_422(cliente):
    l = lote()
    l["mediciones"][0]["unidad"] = "W"
    assert cliente.post("/api/lotes", json=l, headers=token(cliente)).status_code == 422


def test_variable_de_otra_sede_422(cliente):
    l = lote(sede="oficina_rm")
    l["mediciones"].append({"variable": "uv", "valor": 3, "unidad": "índice"})
    h = token(cliente, "gw-oficina-rm", "secreto-rm")
    assert cliente.post("/api/lotes", json=l, headers=h).status_code == 422


def test_valor_fuera_de_rango_422(cliente):
    assert cliente.post("/api/lotes", json=lote(uv=35), headers=token(cliente)).status_code == 422


def test_ts_sin_zona_422(cliente):
    l = lote()
    l["ts"] = "2026-11-18T18:00:00"
    assert cliente.post("/api/lotes", json=l, headers=token(cliente)).status_code == 422


# ---------------------------------------------------------------- ingesta
def test_lote_valido_y_duplicado(cliente):
    h = token(cliente)
    r1 = cliente.post("/api/lotes", json=lote(), headers=h)
    assert r1.status_code == 201 and r1.json() == {"aceptados": 1, "descartados": 0}
    r2 = cliente.post("/api/lotes", json=[lote(), lote(ts=T0 - timedelta(minutes=15))], headers=h)
    assert r2.json() == {"aceptados": 0, "descartados": 2}


def test_reenvio_de_cola_en_orden(cliente):
    lotes = [lote(ts=T0 + timedelta(minutes=15 * i)) for i in (3, 1, 2, 0)]  # llegan desordenados
    r = cliente.post("/api/lotes", json=lotes, headers=token(cliente))
    assert r.json()["aceptados"] == 4
    serie = cliente.get("/api/mediciones", params={"sede": "planta", "variable": "electricidad"}).json()
    assert [m["ts"] for m in serie] == sorted(m["ts"] for m in serie)


def test_estado_y_extras(cliente):
    cliente.post("/api/lotes", json=lote(uv=6.2), headers=token(cliente))
    estado = {(e["sede"], e["variable"]): e for e in cliente.get("/api/estado").json()}
    assert len(estado) == 5
    assert estado[("planta", "uv")]["max_dia"] == 6.2
    assert estado[("planta", "produccion")]["acumulado_dia"] == 45
    assert all(e["estado"] == "normal" for e in estado.values())


# ---------------------------------------------------------------- reglas y alertas
def test_pico_electrico_genera_y_cierra_alerta(cliente):
    h = token(cliente)
    cliente.post("/api/lotes", json=historial(horas=3, fin=T0 + timedelta(hours=2)), headers=h)
    # Hora actual: 4 intervalos a +35%
    pico = [lote(ts=T0 + timedelta(minutes=15 * i), elec=140 * 1.35) for i in range(1, 5)]
    cliente.post("/api/lotes", json=pico, headers=h)
    estado = {(e["sede"], e["variable"]): e for e in cliente.get("/api/estado").json()}
    assert estado[("planta", "electricidad")]["estado"] == "critico"
    activas = cliente.get("/api/alertas", params={"activas": True}).json()
    assert len(activas) == 1 and activas[0]["variable"] == "electricidad" and "supera en" in activas[0]["mensaje"]
    # Vuelve a la normalidad: el consumo de la hora baja y la alerta se cierra.
    normal = [lote(ts=T0 + timedelta(minutes=15 * i), elec=140) for i in range(5, 9)]
    cliente.post("/api/lotes", json=normal, headers=h)
    assert cliente.get("/api/alertas", params={"activas": True}).json() == []
    assert cliente.get("/api/alertas", params={"activas": False}).json()[0]["activa"] is False


def test_uv_advertencia_luego_critico(cliente):
    h = token(cliente)
    cliente.post("/api/lotes", json=lote(uv=9), headers=h)
    cliente.post("/api/lotes", json=lote(ts=T0 + timedelta(minutes=15), uv=11), headers=h)
    activas = cliente.get("/api/alertas", params={"activas": True}).json()
    assert [a["nivel"] for a in activas] == ["critico"]  # la advertencia se cerró al escalar


def test_sede_sin_datos(cliente, monkeypatch):
    cliente.post("/api/lotes", json=lote(), headers=token(cliente))
    monkeypatch.setattr(config, "CICLO_SEG", 0)  # cualquier espera supera 2 ciclos
    estado = cliente.get("/api/estado").json()
    assert {e["estado"] for e in estado} == {"sin_datos"}
    assert cliente.get("/api/salud").json()["sedes"]["planta"]["sin_datos"] is True


def test_websocket_recibe_eventos(cliente):
    with cliente.websocket_connect("/ws") as ws:
        cliente.post("/api/lotes", json=lote(uv=9), headers=token(cliente))
        tipos = {ws.receive_json()["tipo"], ws.receive_json()["tipo"]}
    assert tipos == {"alerta", "estado"}
