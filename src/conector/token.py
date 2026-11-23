"""El token de acceso del conector: JWT con `jti` y el invitado a mano, separados del `client_id` OAuth.

El SDK usa `AccessToken.client_id` para el cliente OAuth (`/revoke` solo revoca si coincide con el que lo
registró; si no, contesta 200 sin revocar nada), así que el invitado viaja en su propio campo. Vence a los 90 días, sin refresh
(pasado el plazo, el invitado vuelve a poner su código). Cada request se valida además contra la tabla
`credencial` por `jti` (oauth.py), de modo que revocar es una fila y un token revocado da 401 de inmediato.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
from mcp.server.auth.provider import AccessToken

from src.conector.solicitud import ALG, clave

AUD_TOKEN = "conector-token"
SCOPE = "consulta"
DIAS_VIGENCIA = 90


class TokenConector(AccessToken):
    """`client_id` (heredado) = el cliente OAuth que obtuvo la credencial. `invitado` = quién es, nunca mezclados."""

    invitado: str
    jti: str | None = None
    # False cuando no se pudo cotejar con la tabla `credencial` (base no disponible): firma y vencimiento valen, pero ninguna
    # herramienta toca datos con un token así; contesta «base no disponible» (Herramientas.no_verificado).
    verificado: bool = True
    # Versión del aviso de privacidad que aceptó el invitado al autorizar (`credencial.aviso_version`). None = credencial anterior
    # al aviso versionado: rige la promesa vieja y el texto de sus consultas NO se guarda.
    aviso_version: int | None = None


def emitir_jwt(invitado: str, jti: str, ahora: datetime | None = None, dias: int = DIAS_VIGENCIA) -> tuple[str, int]:
    """(JWT firmado, vencimiento en epoch). El token no lleva nada más que el invitado, el `jti` y el alcance."""
    ahora = ahora or datetime.now(timezone.utc)
    vence = ahora + timedelta(days=dias)
    token = jwt.encode({"sub": invitado, "jti": jti, "scope": SCOPE, "aud": AUD_TOKEN, "iat": ahora, "exp": vence},
                       clave(), algorithm=ALG)
    return token, int(vence.timestamp())


def decodificar(token: str) -> dict | None:
    """Los datos del token si la firma, la audiencia y el vencimiento valen; None si no (nunca levanta por un token malo)."""
    try:
        datos = jwt.decode(token, clave(), algorithms=[ALG], audience=AUD_TOKEN)
    except jwt.PyJWTError:
        return None
    return datos if datos.get("jti") and datos.get("sub") and datos.get("scope") == SCOPE else None
