import os
import sys
import tempfile

# Base de datos SQLite temporal para cada corrida de pruebas.
_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = os.getenv("TEST_DATABASE_URL", f"sqlite:///{_tmp}/test.db")
os.environ["FRONTEND_DIR"] = os.path.join(_tmp, "sin_frontend")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture()
def cliente():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with TestClient(app) as c:
        yield c


def token(cliente, gateway="gw-planta", secreto="secreto-planta"):
    r = cliente.post("/api/auth/token", json={"gateway_id": gateway, "secreto": secreto})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
