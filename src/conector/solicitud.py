"""Datos firmados con la clave del conector: la solicitud de autorización y, en `token.py`, el token de acceso.

La solicitud viaja de `/authorize` (lo atiende el SDK) a la pantalla donde se pone el código de invitado, FIRMADA: si viajara en claro,
quien reenvía el enlace podría cambiar `redirect_uri` o `code_challenge` en el medio. Dos decisiones estándar:
vence a los 10 minutos, y lleva una audiencia (`aud`) propia, distinta de la del token, para que una solicitud no pueda presentarse
como token ni al revés. La clave sale de `CONECTOR_FIRMA_SECRET` (variable de entorno); sin ella, o si es corta, el servidor no firma nada.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

ALG = "HS256"
AUD_SOLICITUD = "conector-solicitud"
VIGENCIA = timedelta(minutes=10)
MIN_LARGO_CLAVE = 32


class SolicitudInvalida(Exception):
    """La solicitud venció, fue alterada o no es una solicitud."""


def clave() -> str:
    """La clave de firma. Levanta si falta o es corta: firmar con una clave débil es peor que no arrancar."""
    valor = os.environ.get("CONECTOR_FIRMA_SECRET", "")
    if len(valor) < MIN_LARGO_CLAVE:
        raise RuntimeError(f"CONECTOR_FIRMA_SECRET falta o tiene menos de {MIN_LARGO_CLAVE} caracteres")
    return valor


def firmar(datos: dict[str, Any], aud: str = AUD_SOLICITUD, ahora: datetime | None = None,
           vigencia: timedelta = VIGENCIA) -> str:
    """JWT HS256 con `datos`, `aud`, emisión y vencimiento."""
    ahora = ahora or datetime.now(timezone.utc)
    return jwt.encode({**datos, "aud": aud, "iat": ahora, "exp": ahora + vigencia}, clave(), algorithm=ALG)


def leer(firmado: str, aud: str = AUD_SOLICITUD) -> dict[str, Any]:
    """Los datos de una solicitud vigente y de la audiencia pedida; `SolicitudInvalida` si no."""
    try:
        return jwt.decode(firmado, clave(), algorithms=[ALG], audience=aud)
    except jwt.PyJWTError as exc:
        raise SolicitudInvalida(type(exc).__name__) from exc
