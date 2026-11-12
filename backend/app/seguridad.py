"""Autenticación de gateways con JWT.

1. El gateway intercambia su id + secreto por un token firmado (POST /api/auth/token).
2. Envía cada lote con `Authorization: Bearer <token>`.
3. El token lleva la sede: un gateway no puede enviar datos a nombre de otra sede.
"""
import hmac
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
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
