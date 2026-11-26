"""Carga manual por contingencia: plantilla, validar (sin guardar), confirmar, permisos y efectos."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from app.db import Medicion, SesionLocal
from tests.conftest import token, usuario
from tests.test_api import lote
from tests.test_correos import correos, esperar  # noqa: F401  (fixture con SMTP simulado)

CHILE = ZoneInfo("America/Santiago")
RM = ("gw-oficina-rm", "secreto-rm")
ENCABEZADO = "fecha_hora;sede;variable;valor;unidad"


def ciclo(cliente) -> datetime:
    """Cuarto de hora anterior a la hora simulada de la plataforma (UTC)."""
    h = datetime.fromisoformat(cliente.get("/api/reloj", headers=token(cliente)).json()["hora_simulada"].replace("Z", "+00:00"))
    return h.replace(minute=h.minute - h.minute % 15, second=0, microsecond=0) - timedelta(minutes=15)


def local(dt: datetime) -> str:
    return dt.astimezone(CHILE).strftime("%Y-%m-%d %H:%M")


def archivo(*filas: str) -> bytes:
    return ("﻿" + "\r\n".join([ENCABEZADO, *filas]) + "\r\n").encode("utf-8")


def validar(cliente, contenido: bytes, quien="admin"):
    return cliente.post("/api/carga-manual/validar", headers=usuario(cliente, quien),
                        files={"archivo": ("lecturas.csv", contenido, "text/csv")})


def confirmar(cliente, id_carga, quien="admin"):
    return cliente.post("/api/carga-manual/confirmar", json={"id_carga": id_carga}, headers=usuario(cliente, quien))


def mediciones_guardadas() -> int:
    with SesionLocal() as s:
        return s.scalar(select(func.count()).select_from(Medicion))


def test_plantilla_por_sede_y_ejemplos_ignorados(cliente):
    def variables(sede, quien="admin"):
        r = cliente.get("/api/carga-manual/plantilla", params={"sede": sede}, headers=usuario(cliente, quien))
        assert r.status_code == 200 and r.content.startswith("﻿".encode())
        assert r.headers["content-disposition"] == f'attachment; filename="induplac_plantilla_carga_{sede}.csv"'
        lineas = r.content.decode("utf-8-sig").splitlines()
        assert lineas[0] == ENCABEZADO and all(l.startswith("#") for l in lineas[1:])
        return r.content, [l.split(";")[2] for l in lineas[1:] if l.count(";") == 4]

    contenido, rm = variables("oficina_rm")
    assert rm == ["electricidad", "agua", "hh_sin_incidentes"]  # la Oficina RM no tiene producción ni UV
    assert variables("planta")[1] == ["electricidad", "agua", "produccion", "hh_sin_incidentes", "uv"]
    assert variables("planta", "prevencion")[1] == ["hh_sin_incidentes"]
    r = validar(cliente, contenido).json()  # los ejemplos empiezan con # y se ignoran
    assert (r["filas_validas"], r["filas_con_error"], r["filas_duplicadas"]) == (0, 0, 0)


def test_validar_no_guarda_nada(cliente):
    t = ciclo(cliente)
    antes = mediciones_guardadas()
    r = validar(cliente, archivo(f"{local(t)};oficina_rm;electricidad;21,4;kWh", f"{local(t)};planta;uv;6,5;índice"))
    assert r.status_code == 200 and r.json()["filas_validas"] == 2 and r.json()["id_carga"]
    assert mediciones_guardadas() == antes


def test_detecta_filas_invalidas(cliente):
    t = ciclo(cliente)
    r = validar(cliente, archivo(
        f"{local(t)};oficina_rm;uv;5;índice",                         # 2: variable que la RM no mide
        f"{local(t)};planta;electricidad;140;W",                     # 3: unidad incorrecta
        f"{local(t)};planta;uv;25;índice",                           # 4: fuera de rango
        f"{local(t)[:-2]}07;planta;agua;900;L",                      # 5: minutos fuera del ciclo
        f"{local(t + timedelta(days=1))};planta;agua;900;L",          # 6: futuro
        f"{local(t - timedelta(days=91))};planta;agua;900;L",         # 7: más de 90 días
        f"{local(t)};Planta Valparaíso;Agua;880;L",                   # 8: válida (nombres de la exportación)
    )).json()
    motivos = {e["fila"]: e["motivo"] for e in r["errores"]}
    assert "uv no se mide en oficina_rm" in motivos[2]
    assert "unidad" in motivos[3] and "fuera de rango" in motivos[4]
    assert "minutos" in motivos[5] and "futuro" in motivos[6] and "90 días" in motivos[7]
    assert r["filas_validas"] == 1 and r["filas_con_error"] == 6


def test_fila_existente_es_duplicada_y_no_se_guarda(cliente):
    t = ciclo(cliente)
    cliente.post("/api/lotes", json=lote(sede="oficina_rm", ts=t), headers=token(cliente, *RM))
    r = validar(cliente, archivo(f"{local(t)};oficina_rm;agua;900;L")).json()
    assert (r["filas_validas"], r["filas_duplicadas"], r["duplicadas"]) == (0, 1, [2])
    antes = mediciones_guardadas()
    assert confirmar(cliente, r["id_carga"]).json() == {"guardadas": 0, "descartadas": 1}
    assert mediciones_guardadas() == antes


def test_id_de_carga_inexistente_o_vencido(cliente, monkeypatch):
    r = confirmar(cliente, "no-existe")
    assert r.status_code == 404 and "venció" in r.json()["detail"]
    from app import carga
    monkeypatch.setattr(carga, "VIGENCIA_SEG", -1)  # vence apenas se crea
    id_carga = validar(cliente, archivo(f"{local(ciclo(cliente))};planta;agua;900;L")).json()["id_carga"]
    assert confirmar(cliente, id_carga).status_code == 404


def test_permisos_por_rol(cliente):
    t = ciclo(cliente)
    r = validar(cliente, archivo(f"{local(t)};planta;electricidad;140;kWh",
                                 f"{local(t)};planta;hh_sin_incidentes;96000;h"), "prevencion").json()
    assert r["filas_validas"] == 1 and "no puede cargar" in r["errores"][0]["motivo"]
    assert validar(cliente, archivo(), "personal_rm").status_code == 403
    assert cliente.get("/api/carga-manual/plantilla", params={"sede": "planta"},
                       headers=usuario(cliente, "personal_planta")).status_code == 403
    gw = cliente.post("/api/carga-manual/validar", headers=token(cliente),
                      files={"archivo": ("x.csv", archivo(), "text/csv")})
    assert gw.status_code == 401


def test_lecturas_atrasadas_no_abren_alertas_ni_envian_correos(cliente, correos):  # noqa: F811
    t = ciclo(cliente)
    cliente.post("/api/lotes", json=lote(ts=t, uv=5), headers=token(cliente))
    r = validar(cliente, archivo(f"{local(t - timedelta(hours=2))};planta;uv;12;índice")).json()
    assert confirmar(cliente, r["id_carga"]).json() == {"guardadas": 1, "descartadas": 0}
    assert cliente.get("/api/alertas", headers=usuario(cliente)).json() == []
    estado = {e["variable"]: e for e in cliente.get("/api/estado", headers=usuario(cliente)).json()}
    assert estado["uv"]["valor"] == 5  # sigue la lectura más nueva
    assert esperar(correos, 1) == []
    serie = cliente.get("/api/mediciones", params={"sede": "planta", "variable": "uv"}, headers=usuario(cliente)).json()
    assert [m["valor"] for m in serie] == [12, 5]  # el historial quedó completo


def test_lectura_mas_reciente_actualiza_el_estado(cliente):
    t = ciclo(cliente)
    cliente.post("/api/lotes", json=lote(ts=t - timedelta(hours=1), uv=5), headers=token(cliente))
    r = validar(cliente, archivo(f"{local(t)};planta;uv;9,5;índice")).json()
    confirmar(cliente, r["id_carga"])
    estado = {e["variable"]: e for e in cliente.get("/api/estado", headers=usuario(cliente)).json()}
    assert estado["uv"]["valor"] == 9.5 and estado["uv"]["estado"] == "advertencia"
    assert estado["electricidad"]["valor"] == 140  # las demás variables no cambian


def test_csv_exportado_y_recargado_es_todo_duplicado(cliente):
    t = ciclo(cliente)
    cliente.post("/api/lotes", json=[lote(ts=t - timedelta(minutes=15)), lote(ts=t)], headers=token(cliente))
    exportado = cliente.get("/api/exportar/mediciones", headers=usuario(cliente), params={
        "desde": (t - timedelta(hours=1)).isoformat(), "hasta": t.isoformat()}).content
    r = validar(cliente, exportado).json()
    assert (r["filas_validas"], r["filas_con_error"], r["filas_duplicadas"]) == (0, 0, 10)


def test_cada_carga_queda_en_la_auditoria(cliente):
    t = ciclo(cliente)
    r = validar(cliente, archivo(f"{local(t)};planta;agua;900;L"), "jefatura").json()
    confirmar(cliente, r["id_carga"], "jefatura")
    registro = cliente.get("/api/auditoria", headers=usuario(cliente)).json()
    acciones = {a["accion"]: a for a in registro if a["usuario"] == "jefatura"}
    assert acciones["carga_validacion"]["detalle"]["archivo"] == "lecturas.csv"
    assert acciones["carga_confirmacion"]["detalle"]["guardadas"] == 1
    assert acciones["carga_confirmacion"]["detalle"]["sedes"] == ["planta"]
