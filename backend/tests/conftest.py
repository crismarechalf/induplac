import os
import sys
import tempfile

# Base de datos SQLite temporal para cada corrida de pruebas.
_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = os.getenv("TEST_DATABASE_URL", f"sqlite:///{_tmp}/test.db")
os.environ["FRONTEND_DIR"] = os.path.join(_tmp, "sin_frontend")
os.environ.setdefault("JWT_SECRET", "x" * 40)  # clave solo para las pruebas
os.environ["ADMIN_USUARIO"] = "admin"
os.environ["ADMIN_CLAVE"] = "clave-admin"
os.environ["USUARIOS_CLAVE"] = "clave-usuarios"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import notificador, seguridad, simulacion  # noqa: E402
from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402

CLAVES = {"admin": "clave-admin"}


@pytest.fixture()
def cliente():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    simulacion.restablecer()
    notificador.reiniciar()
    seguridad.reiniciar_bloqueos()
    with TestClient(app) as c:  # al arrancar crea los 5 usuarios iniciales
        yield c


def token(cliente, gateway="gw-planta", secreto="secreto-planta"):
    """Cabecera con el token de un gateway."""
    r = cliente.post("/api/auth/token", json={"gateway_id": gateway, "secreto": secreto})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def token_usuario(cliente, usuario="admin") -> str:
    r = cliente.post("/api/auth/login", json={"usuario": usuario, "clave": CLAVES.get(usuario, "clave-usuarios")})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def usuario(cliente, nombre="admin"):
    """Cabecera con el token de un usuario del dashboard (por defecto, admin)."""
    return {"Authorization": f"Bearer {token_usuario(cliente, nombre)}"}
