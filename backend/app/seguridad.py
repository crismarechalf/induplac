"""Autenticación.

Gateways (JWT):
1. El gateway intercambia su id + secreto por un token firmado (POST /api/auth/token).
2. Envía cada lote con `Authorization: Bearer <token>`.
3. El token lleva la sede: un gateway no puede enviar datos a nombre de otra sede.

Panel "Demo" (HTTP Basic): usuario y contraseña de DEMO_USUARIO / DEMO_CLAVE.
"""
import base64
import binascii
import hmac
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import config

_bearer = HTTPBearer(auto_error=False)


def emitir_token(gateway_id: str, secreto: str) -> str:
    credencial = config.GATEWAYS.get(gateway_id)
    # compare_digest evita filtrar información por diferencias de tiempo.
    if not credencial or not hmac.compare_digest(credencial[1], secreto):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Credenciales de gateway inválidas")
    ahora = datetime.now(timezone.utc)
    datos = {"sub": gateway_id, "sede": credencial[0], "iat": ahora,
             "exp": ahora + timedelta(minutes=config.JWT_MINUTOS)}
    return jwt.encode(datos, config.JWT_SECRET, algorithm="HS256")


def gateway_actual(cred: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> dict:
    if cred is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Falta el token Bearer",
                            headers={"WWW-Authenticate": "Bearer"})
    try:
        return jwt.decode(cred.credentials, config.JWT_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token expirado")
    except jwt.InvalidTokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token inválido")


def operador_demo(request: Request) -> None:
    """Valida `Authorization: Basic` contra DEMO_USUARIO / DEMO_CLAVE.

    Se decodifica a mano (UTF-8) para aceptar tildes y ñ. El 401 va sin
    `WWW-Authenticate`: así el navegador no abre su ventana de login y el panel
    muestra su propio formulario.
    """
    esquema, _, valor = request.headers.get("authorization", "").partition(" ")
    try:
        usuario, separador, clave = base64.b64decode(valor, validate=True).decode("utf-8").partition(":")
    except (binascii.Error, UnicodeDecodeError):
        usuario = separador = clave = ""
    configurado = bool(config.DEMO_USUARIO and config.DEMO_CLAVE)
    # Se comparan ambos siempre (& en vez de and) para no filtrar cuál de los dos falló.
    coincide = (hmac.compare_digest(usuario.encode(), config.DEMO_USUARIO.encode())
                & hmac.compare_digest(clave.encode(), config.DEMO_CLAVE.encode()))
    if not (esquema.lower() == "basic" and separador and configurado and coincide):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Usuario o contraseña de demo incorrectos")
