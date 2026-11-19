"""Escenarios de la demo que se controlan desde el panel "Demo" del dashboard.

El estado vive en memoria del proceso (no en la base): es solo para la
presentación y vuelve a la operación normal si la API se reinicia.
Cada gateway lo consulta en cada ciclo (GET /api/simulacion/{sede}) y lo aplica
a sus medidores, con la misma semántica que el simulador del frontend.
"""
ESCENARIOS = ("picoElectrico", "picoAgua", "uvAlto")
ACCIONES = ESCENARIOS + ("normal", "desconectar", "reconectar", "registrarIncidente", "restablecer")
ACCIONES_CON_SEDE = ("desconectar", "registrarIncidente")

_activos: set[str] = set()
_desconectadas: set[str] = set()
_incidentes: dict[str, int] = {}


def reiniciar() -> None:
    _activos.clear()
    _desconectadas.clear()
    _incidentes.clear()


def resumen() -> dict:
    """Lo que muestra el panel: escenarios activos y sedes desconectadas."""
    return {"activos": [e for e in ESCENARIOS if e in _activos], "desconectadas": sorted(_desconectadas)}


def aplicar(accion: str, sede: str | None = None) -> dict:
    if accion in ESCENARIOS:          # acumulables
        _activos.add(accion)
    elif accion == "normal":          # apaga los escenarios, no reconecta
        _activos.clear()
    elif accion == "desconectar":     # la sede deja de enviar lotes (sigue midiendo y encolando)
        _desconectadas.add(sede)
    elif accion == "reconectar":      # todas vuelven a enviar y vacían su cola
        _desconectadas.clear()
    elif accion == "registrarIncidente":
        _incidentes[sede] = _incidentes.get(sede, 0) + 1
    elif accion == "restablecer":     # estado base con un clic: normal + reconectar
        _activos.clear()
        _desconectadas.clear()
    return resumen()


def para_sede(sede: str) -> dict:
    """Instrucciones para el gateway de una sede (la ruta ya validó la sede)."""
    return {
        "pico_electrico": "picoElectrico" in _activos and sede == "planta",
        "pico_agua": "picoAgua" in _activos and sede == "oficina_rm",
        "uv_forzado": 9 if "uvAlto" in _activos and sede == "planta" else None,
        "desconectado": sede in _desconectadas,
        "incidente_id": _incidentes.get(sede, 0),
    }
