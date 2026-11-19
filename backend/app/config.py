"""Configuración leída desde variables de entorno (.env en Docker Compose).

Ningún secreto vive en el código: el repositorio solo trae .env.example.
"""
import os


def _int(nombre: str, defecto: int) -> int:
    return int(os.getenv(nombre, defecto))


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./induplac.db")

# JWT que firma los tokens entregados a los gateways. Obligatorio y sin valor por defecto:
# con una clave conocida cualquiera podría firmar tokens y enviar lotes a nombre de una sede.
JWT_SECRET = os.getenv("JWT_SECRET", "")
if len(JWT_SECRET) < 32 or JWT_SECRET.lower().startswith("cambiar"):  # CAMBIAR = marcador de .env.example
    raise RuntimeError("Falta JWT_SECRET, tiene menos de 32 caracteres o es el de ejemplo: defínelo en .env")
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
# Puerto 587 = STARTTLS; 465 = SSL directo (por si la red bloquea el 587).
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = _int("SMTP_PORT", 587)
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
# Varios correos separados por coma. Vacío = se avisa a SMTP_USER.
ALERTA_DESTINO = os.getenv("ALERTA_DESTINO", "")
# Como máximo 1 correo por (sede, variable) cada N minutos reales.
ALERTA_ENFRIAMIENTO_MIN = _int("ALERTA_ENFRIAMIENTO_MIN", 10)
# Dirección del dashboard que va en los correos.
URL_PUBLICA = os.getenv("URL_PUBLICA", "")

# Usuario y contraseña del panel "Demo" (POST /api/simulacion). Sin ambos, nadie puede usarlo.
DEMO_USUARIO = os.getenv("DEMO_USUARIO", "")
DEMO_CLAVE = os.getenv("DEMO_CLAVE", "")
# Los marcadores CAMBIAR de .env.example cuentan como "sin configurar".
if "CAMBIAR" in (DEMO_USUARIO, DEMO_CLAVE):
    DEMO_USUARIO = DEMO_CLAVE = ""

# Mediciones que se conservan, en días del reloj de las lecturas (simulado en la demo).
# Nunca menos de 29: la regla de consumo necesita 4 semanas + 1 h de historial.
RETENCION_DIAS = max(_int("RETENCION_DIAS", 60), 29)

FRONTEND_DIR = os.getenv("FRONTEND_DIR", os.path.join(os.path.dirname(__file__), "..", "..", "frontend"))
