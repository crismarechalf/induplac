"""Reloj de simulación único: dos gateways desfasados quedan con el mismo ts al seguir al servidor."""
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "gateway"))
import gateway  # noqa: E402

from tests.conftest import token  # noqa: E402


def test_dos_gateways_desfasados_quedan_alineados():
    planta = datetime(2026, 11, 18, 1, 45, tzinfo=timezone.utc)  # el desfase que se veía en el dashboard
    rm = datetime(2026, 11, 18, 2, 45, tzinfo=timezone.utc)
    servidor = datetime(2026, 11, 18, 2, 52, 30, tzinfo=timezone.utc)
    pasos_planta = gateway.pasos_a_generar(planta, servidor)
    pasos_rm = gateway.pasos_a_generar(rm, servidor)
    assert pasos_planta[-1] == datetime(2026, 11, 18, 2, 45, tzinfo=timezone.utc) and len(pasos_planta) == 4
    assert pasos_rm == []  # ya estaba en esa hora: espera el siguiente ciclo
    # Ciclo siguiente: ambas generan exactamente el mismo ts.
    siguiente = servidor + timedelta(minutes=15)
    assert gateway.pasos_a_generar(pasos_planta[-1], siguiente) == gateway.pasos_a_generar(rm, siguiente) == [
        datetime(2026, 11, 18, 3, 0, tzinfo=timezone.utc)]
    # Muy atrasado (gateway detenido): salta a la hora actual; sin servidor: sigue con su reloj.
    assert gateway.pasos_a_generar(planta - timedelta(days=1), servidor) == [gateway.piso_15min(servidor)]
    assert gateway.pasos_a_generar(planta, None) == [planta + timedelta(minutes=15)]


def test_ambos_gateways_leen_la_misma_hora_del_servidor(cliente):
    horas = {cliente.get("/api/reloj", headers=h).json()["hora_simulada"][:16]
             for h in (token(cliente), token(cliente, "gw-oficina-rm", "secreto-rm"))}
    assert len(horas) == 1
