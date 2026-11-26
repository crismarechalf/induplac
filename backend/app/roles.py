"""Roles de usuario: qué ve cada uno (vista), qué puede hacer (permisos) y qué puede
cargar a mano en una contingencia (carga).

El servidor filtra con esta tabla estado, alertas, mediciones, incidentes y eventos
WebSocket. El frontend arma la pantalla con la vista que le entrega el login.
"""
from .catalogo import PUNTOS

TODO = {sede: tuple(variables) for sede, variables in PUNTOS.items()}

ROLES: dict[str, dict] = {
    "admin": {
        "nombre": "Administrador",
        "vista": TODO,
        "permisos": {"consola", "auditoria", "incidentes_ver", "incidentes_registrar", "carga_manual"},
        "carga": TODO,
    },
    "jefatura": {
        "nombre": "Jefatura de operaciones",
        "vista": TODO,
        "permisos": {"incidentes_ver", "carga_manual"},
        "carga": TODO,
    },
    "prevencion": {
        "nombre": "Prevención de riesgos",
        # La Oficina RM no tiene sensor UV: solo sus HH.
        "vista": {"oficina_rm": ("hh_sin_incidentes",), "planta": ("hh_sin_incidentes", "uv")},
        "permisos": {"incidentes_ver", "incidentes_registrar", "carga_manual"},
        # Solo HH: el UV viene de un sensor y no se anota a mano.
        "carga": {"oficina_rm": ("hh_sin_incidentes",), "planta": ("hh_sin_incidentes",)},
    },
    "personal_rm": {
        "nombre": "Personal Oficina RM",
        "vista": {"oficina_rm": TODO["oficina_rm"]},
        "permisos": set(),
    },
    "personal_planta": {
        "nombre": "Personal Planta",
        "vista": {"planta": TODO["planta"]},
        "permisos": set(),
    },
}


def vista(rol: str) -> dict[str, tuple[str, ...]]:
    return ROLES[rol]["vista"]


def puede_ver(rol: str, sede: str, variable: str) -> bool:
    return variable in ROLES[rol]["vista"].get(sede, ())


def tiene_permiso(rol: str, permiso: str) -> bool:
    return permiso in ROLES[rol]["permisos"]


def puede_cargar(rol: str, sede: str, variable: str) -> bool:
    return variable in ROLES[rol].get("carga", {}).get(sede, ())
