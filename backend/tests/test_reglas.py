"""Pruebas unitarias de las reglas de negocio (sin base de datos)."""
from datetime import datetime, timedelta

from app import reglas

FIN = datetime(2026, 11, 18, 15, 0)  # miércoles 15:00


def serie_con(hora_actual: float, hora_historica: float) -> dict:
    """Serie donde cada intervalo de la hora actual vale hora_actual/4 y las 4 semanas previas hora_historica/4."""
    serie = {}
    for t in reglas.instantes_hora(FIN):
        serie[t] = hora_actual / 4
    for k in range(1, 5):
        for t in reglas.instantes_hora(FIN - k * reglas.SEMANA):
            serie[t] = hora_historica / 4
    return serie


def test_consumo_normal_bajo_el_umbral():
    s = serie_con(119, 100)  # +19%
    assert reglas.evaluar_consumo(reglas.consumo_hora(s, FIN), reglas.referencia_hora(s, FIN)) == "normal"


def test_consumo_critico_sobre_el_20_por_ciento():
    s = serie_con(121, 100)  # +21%
    assert reglas.evaluar_consumo(reglas.consumo_hora(s, FIN), reglas.referencia_hora(s, FIN)) == "critico"


def test_justo_20_por_ciento_no_alerta():
    s = serie_con(120, 100)  # exactamente +20%: la regla dice "supera"
    assert reglas.evaluar_consumo(reglas.consumo_hora(s, FIN), reglas.referencia_hora(s, FIN)) == "normal"


def test_sin_historial_no_alerta():
    s = {t: 999 for t in reglas.instantes_hora(FIN)}
    assert reglas.referencia_hora(s, FIN) is None
    assert reglas.evaluar_consumo(reglas.consumo_hora(s, FIN), None) == "normal"


def test_hora_incompleta_no_se_evalua():
    s = serie_con(500, 100)
    del s[FIN - timedelta(minutes=30)]
    assert reglas.consumo_hora(s, FIN) is None


def test_referencia_usa_semanas_disponibles():
    s = serie_con(100, 100)
    for t in reglas.instantes_hora(FIN - 4 * reglas.SEMANA):  # falta la semana 4
        del s[t]
    assert reglas.referencia_hora(s, FIN) == 100


def test_uv_niveles_oms():
    assert reglas.evaluar_uv(7.9) == "normal"
    assert reglas.evaluar_uv(8) == "advertencia"
    assert reglas.evaluar_uv(10.9) == "advertencia"
    assert reglas.evaluar_uv(11) == "critico"


def test_mensaje_consumo_formato_chileno():
    m = reglas.mensaje_consumo(1250, 1000, "kWh", 2, "electricidad")
    assert "1.250,0 kWh" in m and "25,0%" in m and "miércoles" in m


# ------------------------------------------------ piso de exceso absoluto (issue #2)
def test_exceso_bajo_el_piso_no_alerta():
    # Agua de noche en la Oficina RM: 50 L vs 40 L es +25%, pero solo 10 L de exceso (piso 48 L).
    assert reglas.evaluar_consumo(50, 40, piso=48) == "normal"


def test_exceso_sobre_el_piso_alerta():
    # Agua en turno: 600 L vs 480 L es +25% y 120 L de exceso (sobre el piso de 48 L).
    assert reglas.evaluar_consumo(600, 480, piso=48) == "critico"


# ------------------------------------------------ línea de producción detenida
LUNES_10 = datetime(2026, 11, 16, 10, 0)  # lunes 10:00, dentro del turno de la Planta


def test_linea_detenida_en_turno_es_advertencia():
    lecturas = [(LUNES_10, 0, True), (LUNES_10 + timedelta(minutes=15), 0, True)]
    estado, desde = reglas.evaluar_produccion(lecturas)
    assert estado == "advertencia" and desde == LUNES_10
    assert reglas.mensaje_linea_detenida(desde) == "Línea de producción detenida desde 10:00."


def test_linea_detenida_requiere_2_lecturas_en_turno():
    t1 = LUNES_10 + timedelta(minutes=15)
    assert reglas.evaluar_produccion([(LUNES_10, 40, True), (t1, 0, True)])[0] == "normal"   # 1 sola en 0
    assert reglas.evaluar_produccion([(LUNES_10, 0, False), (t1, 0, False)])[0] == "normal"  # fuera de turno
    assert reglas.evaluar_produccion([(LUNES_10, 0, True), (t1, 45, True)])[0] == "normal"   # volvió a producir
    assert reglas.evaluar_produccion([(LUNES_10, 0, True)])[0] == "normal"
    assert reglas.en_turno(((0, 1, 2, 3, 4, 5), 6, 22), LUNES_10)
    assert not reglas.en_turno(((0, 1, 2, 3, 4, 5), 6, 22), datetime(2026, 11, 22, 10, 0))  # domingo
