"""Exportación a CSV: filtrado por rol, validación del período, formato para Excel e inyección CSV."""
import csv
import io
from datetime import datetime, timedelta, timezone

from tests.conftest import token, usuario
from tests.test_api import T0, lote

RM = ("gw-oficina-rm", "secreto-rm")
PERIODO = {"desde": (T0 - timedelta(days=1)).isoformat(), "hasta": (T0 + timedelta(days=1)).isoformat()}


def exportar(cliente, recurso, quien="admin", headers=None, **params):
    return cliente.get(f"/api/exportar/{recurso}", params={**PERIODO, **params},
                       headers=headers if headers is not None else usuario(cliente, quien))


def filas(respuesta) -> list[list[str]]:
    assert respuesta.status_code == 200, respuesta.text
    return list(csv.reader(io.StringIO(respuesta.content.decode("utf-8-sig")), delimiter=";"))


def cargar(cliente):
    """Lecturas de las dos sedes, con una alerta de UV y una de línea detenida en la Planta."""
    def planta(i, uv=5.0, produccion=45):
        l = lote(ts=T0 + timedelta(minutes=15 * i), elec=140.5, uv=uv)
        next(m for m in l["mediciones"] if m["variable"] == "produccion")["valor"] = produccion
        return l
    cliente.post("/api/lotes", json=[planta(0, uv=9), planta(1, produccion=0), planta(2, produccion=0)],
                 headers=token(cliente))
    cliente.post("/api/lotes", json=lote(sede="oficina_rm"), headers=token(cliente, *RM))


def test_cada_rol_exporta_solo_lo_suyo(cliente):
    cargar(cliente)
    sedes = {f[1] for f in filas(exportar(cliente, "mediciones", "personal_rm"))[1:]}
    assert sedes == {"Oficina RM"}
    assert exportar(cliente, "mediciones", "personal_rm", sede="planta").status_code == 403
    assert exportar(cliente, "auditoria", "personal_planta").status_code == 403
    assert exportar(cliente, "incidentes", "personal_planta").status_code == 403
    # Prevención: solo alertas de HH y UV (no la de línea detenida, que es de producción).
    alertas = filas(exportar(cliente, "alertas", "prevencion"))[1:]
    assert {f[2] for f in alertas} == {"Índice UV"}
    assert exportar(cliente, "alertas", "prevencion", variable="produccion").status_code == 403
    todas = filas(exportar(cliente, "alertas", "jefatura"))[1:]
    assert {f[2] for f in todas} == {"Índice UV", "Producción"}


def test_token_de_gateway_o_sin_token_recibe_401(cliente):
    assert exportar(cliente, "mediciones", headers=token(cliente)).status_code == 401
    assert exportar(cliente, "mediciones", headers={}).status_code == 401


def test_periodo_y_filtros_invalidos_422(cliente):
    largo = {"desde": T0.isoformat(), "hasta": (T0 + timedelta(days=91)).isoformat()}
    assert cliente.get("/api/exportar/mediciones", params=largo, headers=usuario(cliente)).status_code == 422
    invertido = {"desde": T0.isoformat(), "hasta": (T0 - timedelta(hours=1)).isoformat()}
    r = cliente.get("/api/exportar/mediciones", params=invertido, headers=usuario(cliente))
    assert r.status_code == 422 and "posterior" in r.json()["detail"]
    assert cliente.get("/api/exportar/mediciones", headers=usuario(cliente)).status_code == 422  # sin período
    assert exportar(cliente, "mediciones", sede="oficina_rm", variable="uv").status_code == 422
    sin_zona = {"desde": "2026-11-17T00:00:00", "hasta": "2026-11-19T00:00:00"}
    assert cliente.get("/api/exportar/mediciones", params=sin_zona, headers=usuario(cliente)).status_code == 422
    assert exportar(cliente, "auditoria", sede="planta").status_code == 422


def test_formato_csv_para_excel(cliente):
    cargar(cliente)
    r = exportar(cliente, "mediciones", sede="planta", variable="electricidad")
    assert r.content.startswith("﻿".encode())                     # BOM
    assert r.headers["content-type"] == "text/csv; charset=utf-8"
    disposicion = r.headers["content-disposition"]
    assert disposicion.startswith('attachment; filename="induplac_mediciones_planta_') and disposicion.endswith('.csv"')
    contenido = r.content.decode("utf-8-sig")
    assert contenido.splitlines()[0] == "fecha_hora;sede;variable;valor;unidad"
    primera = filas(r)[1]
    # T0 = 18:00 UTC = 15:00 en Chile (horario de verano, UTC-3).
    assert primera == ["2026-11-18 15:00", "Planta Valparaíso", "Electricidad", "140,5", "kWh"]


def test_inyeccion_csv_en_incidentes(cliente):
    peligrosa = "=HYPERLINK(\"http://malo\") corte en la línea 2"
    cliente.post("/api/incidentes", headers=usuario(cliente, "prevencion"), json={
        "sede": "planta", "tipo": "Cuasi accidente", "descripcion": peligrosa,
        "ts": datetime.now(timezone.utc).isoformat()})
    ahora = datetime.now(timezone.utc)
    r = cliente.get("/api/exportar/incidentes", headers=usuario(cliente, "jefatura"),
                    params={"desde": (ahora - timedelta(days=1)).isoformat(), "hasta": (ahora + timedelta(minutes=1)).isoformat()})
    fila = filas(r)[1]
    assert fila[3] == "'" + peligrosa and fila[2] == "Cuasi accidente"


def test_cada_exportacion_queda_en_la_auditoria(cliente):
    cargar(cliente)
    exportar(cliente, "mediciones", "personal_rm")
    registro = cliente.get("/api/auditoria", headers=usuario(cliente)).json()
    exportacion = next(a for a in registro if a["accion"] == "exportacion")
    assert exportacion["usuario"] == "personal_rm"
    assert exportacion["detalle"]["recurso"] == "mediciones" and exportacion["detalle"]["sede"] == "todas"
    assert exportacion["detalle"]["filas"] == 3  # electricidad, agua y HH de la Oficina RM
