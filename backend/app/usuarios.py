"""Usuarios del dashboard: semilla inicial y cambio de clave por consola.

Semilla (solo si la tabla está vacía):
  ADMIN_USUARIO (por defecto "admin") con ADMIN_CLAVE, y jefatura, prevencion,
  personal_rm y personal_planta con USUARIOS_CLAVE.

Cambiar una clave sin tocar código (dentro del contenedor):
    python -m app.usuarios cambiar-clave <usuario>
"""
import getpass
import logging
import sys
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import config, roles
from .db import SesionLocal, Usuario, crear_tablas
from .seguridad import hash_clave

log = logging.getLogger("induplac.usuarios")

# usuario → (rol, sede)
INICIALES = {
    "jefatura": ("jefatura", None),
    "prevencion": ("prevencion", None),
    "personal_rm": ("personal_rm", "oficina_rm"),
    "personal_planta": ("personal_planta", "planta"),
}


def _ahora() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def sembrar(s: Session) -> int:
    """Crea los 5 usuarios iniciales si no hay ninguno. Devuelve cuántos creó."""
    if s.scalar(select(func.count()).select_from(Usuario)):
        return 0
    nuevos = []
    if config.ADMIN_CLAVE:
        nuevos.append(Usuario(usuario=config.ADMIN_USUARIO, nombre=roles.ROLES["admin"]["nombre"], rol="admin",
                              sede=None, hash=hash_clave(config.ADMIN_CLAVE), activo=True, creado=_ahora()))
    else:
        log.error("Falta ADMIN_CLAVE (o DEMO_CLAVE): no se creó el usuario administrador")
    if config.USUARIOS_CLAVE:
        for usuario, (rol, sede) in INICIALES.items():
            nuevos.append(Usuario(usuario=usuario, nombre=roles.ROLES[rol]["nombre"], rol=rol, sede=sede,
                                  hash=hash_clave(config.USUARIOS_CLAVE), activo=True, creado=_ahora()))
    else:
        log.error("Falta USUARIOS_CLAVE (o DEMO_CLAVE): no se crearon jefatura, prevencion ni personal")
    s.add_all(nuevos)
    s.commit()
    if nuevos:
        log.info("Usuarios iniciales creados: %s", ", ".join(u.usuario for u in nuevos))
    return len(nuevos)


def cambiar_clave(usuario: str) -> None:
    crear_tablas()
    with SesionLocal() as s:
        u = s.scalar(select(Usuario).where(Usuario.usuario == usuario))
        if not u:
            sys.exit(f"No existe el usuario {usuario!r}")
        clave = getpass.getpass(f"Nueva clave para {usuario}: ")
        if len(clave) < 8:
            sys.exit("La clave debe tener al menos 8 caracteres")
        if clave != getpass.getpass("Repítela: "):
            sys.exit("Las claves no coinciden")
        u.hash = hash_clave(clave)
        s.commit()
    print(f"Clave de {usuario} actualizada")


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "cambiar-clave":
        sys.exit("Uso: python -m app.usuarios cambiar-clave <usuario>")
    cambiar_clave(sys.argv[2])
