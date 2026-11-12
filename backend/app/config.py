"""Configuración leída desde variables de entorno (.env en Docker Compose).

Ningún secreto vive en el código: el repositorio solo trae .env.example.
"""
import os


def _int(nombre: str, defecto: int) -> int:
    return int(os.getenv(nombre, defecto))


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./induplac.db")

# JWT que firma los tokens entregados a los gateways.
JWT_SECRET = os.getenv("JWT_SECRET", "solo-desarrollo-cambiar-en-produccion-0000")
JWT_MINUTOS = _int("JWT_MINUTOS", 60)

# Credencial de cada gateway: id -> (sede, secreto).
GATEWAYS = {
    "gw-oficina-rm": ("oficina_rm", os.getenv("GATEWAY_OFICINA_RM_SECRET", "secreto-rm")),
    "gw-planta": ("planta", os.getenv("GATEWAY_PLANTA_SECRET", "secreto-planta")),
}

# Duración de un ciclo de lectura en segundos reales. Operación real: 900 (15 min).
# En la demo los gateways corren con reloj acelerado y ciclos de 3 s.
CICLO_SEG = _int("CICLO_SEG", 900)
# Una sede pasa a "sin_datos" tras 2 ciclos sin recibir lotes.
CICLOS_SIN_DATOS = 2

# Zona horaria de Induplac: define el "día" de los acumulados y el día de la semana de la regla.
ZONA = os.getenv("ZONA_HORARIA", "America/Santiago")

# Alertas por correo (opcional). Sin SMTP_HOST, las alertas solo quedan en el log.
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = _int("SMTP_PORT", 587)
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
ALERTA_DESTINO = os.getenv("ALERTA_DESTINO", "")

FRONTEND_DIR = os.getenv("FRONTEND_DIR", os.path.join(os.path.dirname(__file__), "..", "..", "frontend"))
