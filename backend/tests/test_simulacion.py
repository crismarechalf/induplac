"""Panel "Demo": POST /api/simulacion (usuario y contraseña) y GET /api/simulacion/{sede} (gateway)."""
import base64

from tests.conftest import token


def basic(usuario="profe", clave="prueba"):
    return {"Authorization": "Basic " + base64.b64encode(f"{usuario}:{clave}".encode()).decode()}


def accion(cliente, nombre, sede=None, auth=None):
    cuerpo = {"accion": nombre} | ({"sede": sede} if sede else {})
    return cliente.post("/api/simulacion", json=cuerpo, headers=basic() if auth is None else auth)


def test_simulacion_exige_usuario_y_clave(cliente):
    assert accion(cliente, "picoElectrico", auth={}).status_code == 401
    assert accion(cliente, "picoElectrico", auth=basic(clave="otra")).status_code == 401
    assert accion(cliente, "picoElectrico", auth=basic(usuario="otro")).status_code == 401
    r = accion(cliente, "picoElectrico", auth={})
    assert "www-authenticate" not in r.headers  # sin ventana de login del navegador
    assert cliente.get("/api/simulacion").json() == {"activos": [], "desconectadas": []}


def test_gateway_solo_consulta_su_sede(cliente):
    assert cliente.get("/api/simulacion/planta").status_code == 401
    assert cliente.get("/api/simulacion/oficina_rm", headers=token(cliente)).status_code == 403
    assert cliente.get("/api/simulacion/planta", headers=token(cliente)).status_code == 200


def test_escenarios_acumulables_y_normal(cliente):
    accion(cliente, "picoElectrico")
    accion(cliente, "picoAgua")
    r = accion(cliente, "uvAlto")
    assert r.status_code == 200 and r.json()["activos"] == ["picoElectrico", "picoAgua", "uvAlto"]
    planta = cliente.get("/api/simulacion/planta", headers=token(cliente)).json()
    rm = cliente.get("/api/simulacion/oficina_rm", headers=token(cliente, "gw-oficina-rm", "secreto-rm")).json()
    assert planta["pico_electrico"] and planta["uv_forzado"] == 9 and not planta["pico_agua"]
    assert rm["pico_agua"] and not rm["pico_electrico"] and rm["uv_forzado"] is None
    accion(cliente, "desconectar", "planta")
    assert accion(cliente, "normal").json() == {"activos": [], "desconectadas": ["planta"]}  # normal no reconecta


def test_desconectar_reconectar_e_incidente(cliente):
    assert accion(cliente, "desconectar").status_code == 422  # requiere sede
    accion(cliente, "desconectar", "oficina_rm")
    h = token(cliente, "gw-oficina-rm", "secreto-rm")
    assert cliente.get("/api/simulacion/oficina_rm", headers=h).json()["desconectado"] is True
    accion(cliente, "registrarIncidente", "oficina_rm")
    accion(cliente, "registrarIncidente", "oficina_rm")
    assert cliente.get("/api/simulacion/oficina_rm", headers=h).json()["incidente_id"] == 2
    accion(cliente, "reconectar")
    assert cliente.get("/api/simulacion/oficina_rm", headers=h).json()["desconectado"] is False


def test_restablecer_vuelve_al_estado_base(cliente):
    accion(cliente, "uvAlto")
    accion(cliente, "desconectar", "planta")
    assert accion(cliente, "restablecer").json() == {"activos": [], "desconectadas": []}
    assert accion(cliente, "explotar").status_code == 422  # acción inexistente
