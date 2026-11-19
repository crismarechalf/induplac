"""Retención: las mediciones de más de RETENCION_DIAS se borran y las recientes se conservan."""
from datetime import timedelta

from app import servicio
from app.db import SesionLocal
from tests.conftest import token, token_usuario, usuario
from tests.test_api import T0, lote


def test_retencion_borra_mediciones_antiguas(cliente):
    h = token(cliente)
    viejas = [lote(ts=T0), lote(ts=T0 + timedelta(minutes=15))]
    recientes = [lote(ts=T0 + timedelta(days=61)), lote(ts=T0 + timedelta(days=61, minutes=15))]
    cliente.post("/api/lotes", json=viejas + recientes, headers=h)
    with SesionLocal() as s:
        assert servicio.podar(s) == 10  # 2 lotes x 5 mediciones
    serie = cliente.get("/api/mediciones", headers=usuario(cliente), params={"sede": "planta", "variable": "electricidad"}).json()
    assert len(serie) == 2 and serie[0]["ts"].startswith("2027-01-18")
