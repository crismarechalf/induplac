"""Consola de operación y pruebas (solo admin) y lo que recibe cada gateway."""
from tests.conftest import token, usuario

RM = ("gw-oficina-rm", "secreto-rm")


def put(cliente, sede, cambios, quien="admin"):
    return cliente.put(f"/api/simulacion/{sede}", json=cambios, headers=usuario(cliente, quien))


def test_consola_solo_admin(cliente):
    assert cliente.get("/api/simulacion").status_code == 401
    for rol in ("jefatura", "prevencion", "personal_planta"):
        h = usuario(cliente, rol)
        assert cliente.get("/api/simulacion", headers=h).status_code == 403
        assert put(cliente, "planta", {"electricidad_pct": 50}, rol).status_code == 403
        assert cliente.post("/api/simulacion/restablecer", headers=h).status_code == 403
    assert cliente.get("/api/simulacion", headers=usuario(cliente)).status_code == 200


def test_consola_valida_rangos(cliente):
    assert put(cliente, "planta", {"electricidad_pct": 105}).status_code == 422
    assert put(cliente, "planta", {"agua_pct": -60}).status_code == 422
    assert put(cliente, "planta", {"produccion_pct": 160}).status_code == 422
    assert put(cliente, "planta", {"uv_forzado": 15}).status_code == 422
    assert put(cliente, "planta", {"explotar": True}).status_code == 422
    assert put(cliente, "planta", {"electricidad_pct": None}).status_code == 422
    assert put(cliente, "planta", {}).status_code == 422


def test_consola_rechaza_variable_inexistente_en_la_sede(cliente):
    # La Oficina RM no tiene línea de producción ni sensor UV.
    assert put(cliente, "oficina_rm", {"uv_forzado": 9}).status_code == 422
    assert put(cliente, "oficina_rm", {"produccion_pct": 50}).status_code == 422
    r = cliente.get("/api/simulacion", headers=usuario(cliente)).json()
    assert r["controles"]["oficina_rm"] == ["electricidad_pct", "agua_pct", "enlace_cortado"]


def test_gateway_recibe_los_cambios_de_su_sede(cliente):
    r = put(cliente, "planta", {"electricidad_pct": 50, "produccion_pct": 0, "uv_forzado": 9.5, "enlace_cortado": True})
    assert r.status_code == 200 and r.json()["sedes"]["planta"]["electricidad_pct"] == 50
    planta = cliente.get("/api/simulacion/planta", headers=token(cliente)).json()
    assert planta == {"electricidad_pct": 50, "agua_pct": 0, "produccion_pct": 0, "uv_forzado": 9.5,
                      "enlace_cortado": True, "incidente_id": 0}
    rm = cliente.get("/api/simulacion/oficina_rm", headers=token(cliente, *RM)).json()
    assert rm["electricidad_pct"] == 0 and rm["enlace_cortado"] is False
    assert cliente.get("/api/simulacion/oficina_rm", headers=token(cliente)).status_code == 403
    assert cliente.get("/api/simulacion/planta").status_code == 401


def test_restablecer_y_registro_de_acciones(cliente):
    put(cliente, "planta", {"uv_forzado": 12})
    put(cliente, "oficina_rm", {"agua_pct": 80})
    r = cliente.post("/api/simulacion/restablecer", headers=usuario(cliente)).json()
    assert r["sedes"]["planta"] == {"electricidad_pct": 0, "agua_pct": 0, "produccion_pct": 100,
                                    "uv_forzado": None, "enlace_cortado": False}
    assert r["sedes"]["oficina_rm"]["agua_pct"] == 0
    assert [a["accion"] for a in r["registro"]] == ["restablecer", "consola", "consola"]
    assert r["registro"][1]["detalle"] == {"sede": "oficina_rm", "agua_pct": 80}
    assert r["registro"][0]["usuario"] == "admin"
