"""Autenticación y autorización.

Gateways (JWT tipo "gateway"):
1. El gateway intercambia su id + secreto por un token firmado (POST /api/auth/token).
2. Envía cada lote con `Authorization: Bearer <token>`.
3. El token lleva la sede: un gateway no puede enviar datos a nombre de otra sede.

Usuarios del dashboard (JWT tipo "usuario", 8 h):
- POST /api/auth/login con usuario y clave (hash scrypt con sal propia, librería estándar).
- El token lleva rol y sede; el servidor filtra todo según el rol (roles.py).
- 5 intentos fallidos de un usuario en 5 minutos → 429 durante 5 minutos.

Un tipo de token nunca sirve donde va el otro.
"""
import hashlib
import hmac
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import config, roles

_bearer = HTTPBearer(auto_error=False)


# ------------------------------------------------------------------ claves
_SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}


def hash_clave(clave: str) -> str:
    sal = secrets.token_bytes(16)
    derivada = hashlib.scrypt(clave.encode(), salt=sal, **_SCRYPT)
    return f"scrypt${sal.hex()}${derivada.hex()}"


def verificar_clave(clave: str, guardado: str) -> bool:
    try:
        _, sal, esperado = guardado.split("$")
        derivada = hashlib.scrypt(clave.encode(), salt=bytes.fromhex(sal), **_SCRYPT)
    except ValueError:
        return False
    return hmac.compare_digest(derivada.hex(), esperado)


# Hash de relleno: un usuario inexistente tarda lo mismo que uno con clave incorrecta.
_HASH_RELLENO = hash_clave(secrets.token_hex(8))


# ------------------------------------------------------------------ bloqueo por intentos
INTENTOS_MAX = 5
VENTANA_SEG = 300

_fallos: dict[str, list[float]] = {}
_candado = threading.Lock()


def reiniciar_bloqueos() -> None:
    with _candado:
        _fallos.clear()


def bloqueado(usuario: str) -> int:
    """Segundos de bloqueo restantes para ese usuario (0 = puede intentar)."""
    ahora = time.monotonic()
    with _candado:
        recientes = [t for t in _fallos.get(usuario, []) if ahora - t < VENTANA_SEG]
        if recientes:
            _fallos[usuario] = recientes
        else:
            _fallos.pop(usuario, None)
        if len(recientes) >= INTENTOS_MAX:
            return int(VENTANA_SEG - (ahora - recientes[-1])) + 1
        return 0


def registrar_fallo(usuario: str) -> None:
    with _candado:
        _fallos.setdefault(usuario, []).append(time.monotonic())


def limpiar_fallos(usuario: str) -> None:
    with _candado:
        _fallos.pop(usuario, None)


def comprobar_clave(clave: str, guardado: str | None) -> bool:
    return verificar_clave(clave, guardado or _HASH_RELLENO) and guardado is not None


# ------------------------------------------------------------------ tokens
def _firmar(datos: dict, duracion: timedelta) -> str:
    ahora = datetime.now(timezone.utc)
    return jwt.encode({**datos, "iat": ahora, "exp": ahora + duracion}, config.JWT_SECRET, algorithm="HS256")


def emitir_token(gateway_id: str, secreto: str) -> str:
    credencial = config.GATEWAYS.get(gateway_id)
    # compare_digest evita filtrar información por diferencias de tiempo.
    if not credencial or not hmac.compare_digest(credencial[1], secreto):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Credenciales de gateway inválidas")
    return _firmar({"sub": gateway_id, "sede": credencial[0], "tipo": "gateway"},
                   timedelta(minutes=config.JWT_MINUTOS))


def emitir_token_usuario(usuario: str, rol: str, sede: str | None) -> str:
    return _firmar({"sub": usuario, "rol": rol, "sede": sede, "tipo": "usuario"},
                   timedelta(hours=config.SESION_HORAS))


def decodificar(token: str, tipo: str) -> dict:
    """Valida firma, vencimiento y tipo. Lanza 401 si algo no calza."""
    try:
        datos = jwt.decode(token, config.JWT_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token expirado")
    except jwt.InvalidTokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token inválido")
    if datos.get("tipo") != tipo or (tipo == "usuario" and datos.get("rol") not in roles.ROLES):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token de otro tipo")
    return datos


def _bearer_de(cred: HTTPAuthorizationCredentials | None) -> str:
    if cred is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Falta el token Bearer",
                            headers={"WWW-Authenticate": "Bearer"})
    return cred.credentials


def gateway_actual(cred: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> dict:
    return decodificar(_bearer_de(cred), "gateway")


def usuario_actual(cred: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> dict:
    return decodificar(_bearer_de(cred), "usuario")


def cualquier_token(cred: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> dict:
    """Usuario o gateway (para el reloj, que lo consultan ambos)."""
    token = _bearer_de(cred)
    try:
        return decodificar(token, "usuario")
    except HTTPException:
        return decodificar(token, "gateway")


def requiere(permiso: str):
    """Dependencia: usuario con ese permiso (403 si su rol no lo tiene)."""
    def dependencia(u: dict = Depends(usuario_actual)) -> dict:
        if not roles.tiene_permiso(u["rol"], permiso):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"El rol {u['rol']} no tiene permiso para esto")
        return u
    return dependencia
