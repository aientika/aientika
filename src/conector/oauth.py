"""Servidor de autorización OAuth del conector: DCR con lista blanca, PKCE, código de un solo uso.

El SDK `mcp` atiende `/register`, `/authorize`, `/token` y `/revoke` y valida la FORMA (PKCE S256, `redirect_uri` exacto, vencimiento
del código). Lo que NO valida —y es donde vive la seguridad— está aquí: la lista blanca de retornos (la barrera contra el robo de
códigos por DCR), el techo de registros por IP, el un-solo-uso del código con revocación ante reuso, el `resource`, y que el refresh
no exista. Lo que `/token` entrega es una credencial con `jti` (tabla `credencial`) de 90 días; cada request a `/mcp` se valida
contra esa tabla, así que revocar es una fila. Cada método abre su propia transacción; la BD (pg8000) es síncrona y corre en hilos.
"""

from __future__ import annotations

import asyncio
import contextvars
import hashlib
import json
import logging
import secrets
from datetime import datetime, timezone

from mcp.server.auth.provider import (AuthorizationCode, AuthorizationParams, AuthorizeError, RefreshToken, RegistrationError,
                                      TokenError)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from src.conector import bd, lista_blanca, limites, solicitud
from src.conector.token import DIAS_VIGENCIA, SCOPE, TokenConector, decodificar, emitir_jwt

logger = logging.getLogger(__name__)

VIGENCIA_CODIGO_S = 300
MAX_REGISTROS_POR_IP_HORA = 20
PURGA_CLIENTES_SIN_USO_S = 24 * 3600
RUTA_PANTALLA = "/conector/autorizar"

# La IP de quien pide `/register`: el handler del SDK no le pasa el request al proveedor, así que el ASGI (asgi.py) la deja acá.
ip_de_la_peticion: contextvars.ContextVar[str | None] = contextvars.ContextVar("ip_de_la_peticion", default=None)


def hash_codigo_autorizacion(code: str) -> str:
    """sha256 del código de autorización: lo único que se guarda."""
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def hash_ip(ip: str | None) -> str | None:
    """La IP no se guarda en claro."""
    return hashlib.sha256(ip.encode("utf-8")).hexdigest() if ip else None


def _utc() -> datetime:
    return datetime.now(timezone.utc)


def revocar_credencial(cur, jti: str, ts: int, motivo: str) -> bool:
    """Marca la credencial como revocada. True si estaba vigente."""
    cur.execute("UPDATE credencial SET revocada_ts = %s, motivo = %s WHERE jti = %s AND revocada_ts IS NULL", (ts, motivo[:120], jti))
    return cur.rowcount > 0


def emitir_codigo(client_id: str, invitado_id: str, datos: dict, ahora: datetime, aviso_version: int | None = None) -> str:
    """Crea el código de autorización de un solo uso (5 min). Lo llama la pantalla, no el SDK, con la versión del aviso de privacidad
    que la persona tuvo delante al autorizar: `/token` la copia a la credencial y de ahí depende si se guarda el texto (registro.py)."""
    code = secrets.token_urlsafe(32)
    with bd.estado() as conn:
        conn.cursor().execute(
            "INSERT INTO oauth_codigo (codigo_sha256, client_id, invitado_id, redirect_uri, redirect_uri_explicita, code_challenge, "
            "scopes, resource, expira_ts, aviso_version) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (hash_codigo_autorizacion(code), client_id, invitado_id, datos["redirect_uri"], bool(datos["redirect_uri_explicita"]),
             datos["code_challenge"], " ".join(datos.get("scopes") or [SCOPE]), datos.get("resource"),
             int(ahora.timestamp()) + VIGENCIA_CODIGO_S, aviso_version))
    return code


class ProveedorConector:
    """`OAuthAuthorizationServerProvider` del conector. `url_publica` fija el `resource` válido; `reloj` se inyecta en las pruebas."""

    def __init__(self, url_publica: str, reloj=_utc):
        self.url_publica = url_publica.rstrip("/")
        self.reloj = reloj

    def recurso_esperado(self) -> str:
        """El `resource` que el cliente debe pedir (RFC 8707): la URL pública del endpoint MCP."""
        return self.url_publica + "/mcp"

    # --- clientes ---------------------------------------------------------------------------------------------------------

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        return await asyncio.to_thread(self._get_client, client_id)

    def _get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        with bd.estado() as conn:
            cur = conn.cursor()
            cur.execute("SELECT registro FROM oauth_cliente WHERE client_id = %s", (client_id,))
            fila = cur.fetchone()
        return OAuthClientInformationFull.model_validate_json(fila[0]) if fila else None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        uris = [str(u) for u in (client_info.redirect_uris or [])]
        if not lista_blanca.redirect_uris_validas(uris):
            logger.warning("[conector-oauth] registro rechazado por la lista blanca de retornos")
            raise RegistrationError("invalid_redirect_uri", "Este conector solo se puede agregar desde Claude.")
        if not await asyncio.to_thread(self._registrar, client_info, uris, ip_de_la_peticion.get()):
            raise RegistrationError("invalid_client_metadata", "Demasiados registros; probá más tarde.")

    def _registrar(self, client_info: OAuthClientInformationFull, uris: list[str], ip: str | None) -> bool:
        ahora = self.reloj()
        ts = int(ahora.timestamp())
        with bd.estado() as conn:
            cur = conn.cursor()
            if ip and not limites.tomar(cur, f"dcr:{hash_ip(ip)}", f"h:{ahora:%Y-%m-%dT%H}", MAX_REGISTROS_POR_IP_HORA):
                return False
            # Contra el flood de DCR: se borran los registros de más de un día que nunca autorizaron nada. Los que tienen
            # credenciales NO: Claude reutiliza el client_id.
            cur.execute("DELETE FROM oauth_cliente WHERE creado_ts < %s AND client_id NOT IN (SELECT client_id FROM credencial)",
                        (ts - PURGA_CLIENTES_SIN_USO_S,))
            cur.execute("INSERT INTO oauth_cliente (client_id, registro, etiqueta, ip_sha256, creado_ts) VALUES (%s, %s, %s, %s, %s)",
                        (client_info.client_id, json.dumps(client_info.model_dump(mode="json", exclude_none=True)),
                         lista_blanca.etiqueta_de(uris), hash_ip(ip), ts))
        return True

    # --- autorización -----------------------------------------------------------------------------------------------------

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        if not params.resource or params.resource.rstrip("/") != self.recurso_esperado():
            raise AuthorizeError("invalid_request", "El recurso pedido no es este conector.")
        firmada = solicitud.firmar({
            "client_id": client.client_id, "redirect_uri": str(params.redirect_uri),
            "redirect_uri_explicita": params.redirect_uri_provided_explicitly, "state": params.state,
            "scopes": params.scopes or [SCOPE], "code_challenge": params.code_challenge, "resource": params.resource})
        # Relativa a propósito: la pantalla se sirve en el mismo host que atendió `/authorize`.
        return f"{RUTA_PANTALLA}?s={firmada}"

    async def load_authorization_code(self, client: OAuthClientInformationFull, authorization_code: str) -> AuthorizationCode | None:
        fila = await asyncio.to_thread(self._leer_codigo, authorization_code)
        if fila is None or fila[0] != client.client_id:
            return None
        # Se devuelve AUNQUE ya se haya usado: el reuso se detecta en el canje, que además revoca lo emitido. Devolver None
        # aquí haría que el SDK contestara invalid_grant sin revocar nada.
        return AuthorizationCode(code=authorization_code, scopes=fila[1].split(), expires_at=float(fila[2]), client_id=fila[0],
                                 code_challenge=fila[3], redirect_uri=fila[4], redirect_uri_provided_explicitly=bool(fila[5]),
                                 resource=fila[6])

    def _leer_codigo(self, code: str):
        with bd.estado() as conn:
            cur = conn.cursor()
            cur.execute("SELECT client_id, scopes, expira_ts, code_challenge, redirect_uri, redirect_uri_explicita, resource "
                        "FROM oauth_codigo WHERE codigo_sha256 = %s", (hash_codigo_autorizacion(code),))
            return cur.fetchone()

    async def exchange_authorization_code(self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode) -> OAuthToken:
        resultado = await asyncio.to_thread(self._canjear, client.client_id, authorization_code.code)
        if isinstance(resultado, str):
            raise TokenError("invalid_grant", resultado)
        token, vence = resultado
        return OAuthToken(access_token=token, expires_in=DIAS_VIGENCIA * 86400, scope=" ".join(authorization_code.scopes))

    def _canjear(self, client_id: str, code: str) -> tuple[str, int] | str:
        """(JWT, vencimiento) o el motivo del rechazo. El rechazo se COMMITEA (revocación por reuso) y recién después se levanta."""
        h, ahora = hash_codigo_autorizacion(code), self.reloj()
        ts = int(ahora.timestamp())
        with bd.estado() as conn:
            cur = conn.cursor()
            # Canje ATÓMICO: el UPDATE condicional decide quién gana. Leer y después escribir dejaría que dos `/token`
            # simultáneos emitieran dos credenciales.
            cur.execute("UPDATE oauth_codigo SET usado_ts = %s WHERE codigo_sha256 = %s AND usado_ts IS NULL AND expira_ts >= %s "
                        "RETURNING invitado_id, aviso_version", (ts, h, ts))
            fila = cur.fetchone()
            if fila is None:
                self._revocar_por_reuso(cur, h, ts)
                return "El código de autorización ya se usó o venció."
            cur.execute("SELECT activo FROM invitado WHERE id = %s", (fila[0],))
            inv = cur.fetchone()
            if not inv or not inv[0]:
                return "El invitado ya no está activo."
            jti = secrets.token_urlsafe(16)
            token, vence = emitir_jwt(fila[0], jti, ahora)
            cur.execute("INSERT INTO credencial (jti, invitado_id, client_id, creado_ts, expira_ts, aviso_version) "
                        "VALUES (%s, %s, %s, %s, %s, %s)", (jti, fila[0], client_id, ts, vence, fila[1]))
            cur.execute("UPDATE oauth_codigo SET jti_emitido = %s WHERE codigo_sha256 = %s", (jti, h))
        logger.info("[conector-oauth] autorizado jti=%s", jti[:8])
        return token, vence

    def _revocar_por_reuso(self, cur, h: str, ts: int) -> None:
        """RFC 6749: un código reusado se filtró; lo que emitió también muere."""
        cur.execute("SELECT jti_emitido FROM oauth_codigo WHERE codigo_sha256 = %s", (h,))
        fila = cur.fetchone()
        if fila and fila[0] and revocar_credencial(cur, fila[0], ts, "el código de autorización se intentó usar dos veces"):
            logger.warning("[conector-oauth] codigo reusado: revocada jti=%s", fila[0][:8])

    # --- refresh: no existe (90 días y volver a poner el código) -----------------------------------------------------------

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str) -> RefreshToken | None:
        return None

    async def exchange_refresh_token(self, client, refresh_token, scopes) -> OAuthToken:
        raise TokenError("unsupported_grant_type", "Este conector no emite refresh tokens.")

    # --- tokens -----------------------------------------------------------------------------------------------------------

    async def load_access_token(self, token: str) -> TokenConector | None:
        """El token de `/mcp` y `/revoke`: firma y vencimiento, y además vigente en la tabla `credencial` (revocada = 401).

        Fuera del horario de atención (si está restringido) o con la base caída no se puede cotejar: el token pasa MARCADO `verificado=False` y las
        herramientas contestan en palabras sin tocar datos. Devolver 401 haría que Claude pidiera volver a autorizar, y un 500 no diría nada.
        """
        datos = decodificar(token)
        if datos is None:
            logger.info("[conector] token rechazado: firma o vencimiento")
            return None
        comun = {"token": token, "scopes": [SCOPE], "expires_at": int(datos["exp"]), "invitado": datos["sub"], "jti": datos["jti"],
                 "resource": self.recurso_esperado()}
        if limites.fuera_de_horario(self.reloj()):
            return TokenConector(client_id="", verificado=False, **comun)
        try:
            vigente = await asyncio.to_thread(self._credencial_vigente, datos["jti"], datos["sub"])
        except bd.BDNoDisponible:
            return TokenConector(client_id="", verificado=False, **comun)
        if vigente is None:
            logger.info("[conector] token rechazado: revocado, vencido en la tabla o invitado inactivo jti=%s", datos["jti"][:8])
            return None
        cliente, aviso = vigente
        return TokenConector(client_id=cliente, aviso_version=aviso, **comun)

    def _credencial_vigente(self, jti: str, invitado: str) -> tuple[str, int | None] | None:
        """(client_id, versión del aviso aceptado) de la credencial vigente, en la misma consulta de siempre; None si no vale."""
        ts = int(self.reloj().timestamp())
        with bd.estado() as conn:
            cur = conn.cursor()
            cur.execute("SELECT c.client_id, c.aviso_version FROM credencial c JOIN invitado i ON i.id = c.invitado_id WHERE c.jti = %s "
                        "AND c.invitado_id = %s AND c.revocada_ts IS NULL AND c.expira_ts > %s AND i.activo = %s",
                        (jti, invitado, ts, True))
            fila = cur.fetchone()
        return (fila[0], fila[1]) if fila else None

    async def revoke_token(self, token: TokenConector | RefreshToken) -> None:
        jti = getattr(token, "jti", None)
        if jti:
            await asyncio.to_thread(self._revocar, jti)

    def _revocar(self, jti: str) -> None:
        with bd.estado() as conn:
            if revocar_credencial(conn.cursor(), jti, int(self.reloj().timestamp()), "revocada por el cliente (/revoke)"):
                logger.info("[conector-oauth] revocada por /revoke jti=%s", jti[:8])

