"""Envoltura ASGI del conector: lo que el SDK de MCP no hace y las buenas prácticas exigen.

1. `/mcp/` y `/mcp` son la misma dirección: el cliente MCP no sigue el 307 que Starlette da por la barra.
2. La IP de quien llama a `/register` se deja en un contextvar: el handler del SDK no se la pasa al proveedor (techo de registros por IP).
3. Refresh NO se anuncia: se quita de `grant_types_supported` en los metadatos. Pero el SDK exige que el cliente se
   registre con `authorization_code` Y `refresh_token`, así que si un cliente se registra sin el segundo se le agrega al vuelo: el
   registro pasa, y el proveedor igual rechaza todo refresh (`load_refresh_token` devuelve None).
4. Fuera del horario de servicio o con la base caída, las rutas OAuth que tocan la base (`/register`, `/authorize`, `/token`, `/revoke`) dan
   503 con un cuerpo OAuth (`temporarily_unavailable` + el mensaje en palabras). Sin esto el SDK dejaba subir `BDNoDisponible` y
   Claude mostraba un 500 opaco antes de abrir la pantalla de autorización.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from src.conector import bd, limites
from src.conector.oauth import ip_de_la_peticion

RUTA_METADATOS = "/.well-known/oauth-authorization-server"
MAX_CUERPO_REGISTRO = 65_536
RUTAS_OAUTH_CON_BASE = frozenset({"/register", "/authorize", "/token", "/revoke"})
ERROR_NO_DISPONIBLE = "temporarily_unavailable"


def ip_de_scope(scope) -> str | None:
    """La última entrada de X-Forwarded-For (la que agrega Google), o la IP del socket."""
    for k, v in scope.get("headers", []):
        if k == b"x-forwarded-for" and v.strip():
            return v.decode("latin-1").split(",")[-1].strip()
    cliente = scope.get("client")
    return cliente[0] if cliente else None


def _con_largo(headers, largo: int) -> list:
    return [(k, v) for k, v in headers if k != b"content-length"] + [(b"content-length", str(largo).encode())]


def completar_grants(cuerpo: bytes) -> bytes:
    """Agrega `refresh_token` a los `grant_types` de un registro que trae `authorization_code` sin él."""
    try:
        datos = json.loads(cuerpo)
    except ValueError:
        return cuerpo
    grants = datos.get("grant_types") if isinstance(datos, dict) else None
    if isinstance(grants, list) and "authorization_code" in grants and "refresh_token" not in grants:
        datos["grant_types"] = [*grants, "refresh_token"]
        return json.dumps(datos).encode()
    return cuerpo


def quitar_refresh(cuerpo: bytes) -> bytes:
    """Quita `refresh_token` de `grant_types_supported` en los metadatos de autorización."""
    try:
        datos = json.loads(cuerpo)
        datos["grant_types_supported"] = [g for g in datos.get("grant_types_supported", []) if g != "refresh_token"]
    except (ValueError, AttributeError):
        return cuerpo
    return json.dumps(datos).encode()


def _cae_la_base(exc: BaseException) -> bool:
    """¿La excepción es (o agrupa) un `BDNoDisponible`? anyio puede envolverla en un ExceptionGroup."""
    if isinstance(exc, bd.BDNoDisponible):
        return True
    grupo = getattr(exc, "exceptions", None)  # BaseExceptionGroup
    return isinstance(grupo, tuple) and any(_cae_la_base(e) for e in grupo)


async def responder_no_disponible(send, mensaje: str) -> None:
    """503 con cuerpo OAuth (RFC 6749): `error` y `error_description` en palabras."""
    cuerpo = json.dumps({"error": ERROR_NO_DISPONIBLE, "error_description": mensaje}, ensure_ascii=False).encode("utf-8")
    await send({"type": "http.response.start", "status": 503, "headers": [
        (b"content-type", b"application/json; charset=utf-8"), (b"cache-control", b"no-store"), (b"retry-after", b"600"),
        (b"content-length", str(len(cuerpo)).encode())]})
    await send({"type": "http.response.body", "body": cuerpo})


class Envoltura:
    """App ASGI que envuelve al app del SDK (ver el docstring del módulo). `oauth=False` en el modo de desarrollo sin autenticación."""

    def __init__(self, app, reloj=lambda: datetime.now(timezone.utc), oauth: bool = True):
        self.app = app
        self.reloj = reloj
        self.oauth = oauth

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        if scope["path"] == "/mcp/":
            scope = {**scope, "path": "/mcp", "raw_path": b"/mcp"}
        if self.oauth and scope["path"] in RUTAS_OAUTH_CON_BASE:
            return await self._oauth_con_base(scope, receive, send)
        if scope["path"] == RUTA_METADATOS:
            return await self._metadatos(scope, receive, send)
        return await self.app(scope, receive, send)

    async def _oauth_con_base(self, scope, receive, send):
        """Corta fuera de horario; dentro, pasa al SDK con la respuesta en búfer para cambiar un 500 por base caída en un 503."""
        if limites.fuera_de_horario(self.reloj()):
            return await responder_no_disponible(send, limites.MENSAJE_FUERA_DE_HORARIO)
        mensajes = []

        async def send_buffer(msg):
            mensajes.append(msg)

        try:
            if scope["path"] == "/register" and scope["method"] == "POST":
                ip_de_la_peticion.set(ip_de_scope(scope))
                await self._registro(scope, receive, send_buffer)
            else:
                await self.app(scope, receive, send_buffer)
        except BaseException as exc:
            # Starlette ya escribió su 500 en el búfer antes de relanzar: se descarta y se contesta en palabras.
            if not _cae_la_base(exc):
                for msg in mensajes:  # cualquier otra falla sale como antes: el 500 de Starlette y la excepción al log
                    await send(msg)
                raise
            return await responder_no_disponible(send, bd.MENSAJE_NO_DISPONIBLE)
        for msg in mensajes:
            await send(msg)

    async def _registro(self, scope, receive, send):
        partes, total = [], 0
        while True:
            msg = await receive()
            partes.append(msg.get("body", b""))
            total += len(partes[-1])
            if total > MAX_CUERPO_REGISTRO:
                await send({"type": "http.response.start", "status": 413, "headers": [(b"content-length", b"0")]})
                return await send({"type": "http.response.body", "body": b""})
            if not msg.get("more_body"):
                break
        cuerpo = completar_grants(b"".join(partes))
        scope = {**scope, "headers": _con_largo(scope["headers"], len(cuerpo))}
        enviado = False

        async def receive_nuevo():
            nonlocal enviado
            if enviado:
                return await receive()
            enviado = True
            return {"type": "http.request", "body": cuerpo, "more_body": False}

        await self.app(scope, receive_nuevo, send)

    async def _metadatos(self, scope, receive, send):
        inicio, partes = {}, []

        async def send_buffer(msg):
            if msg["type"] == "http.response.start":
                inicio.update(msg)
            else:
                partes.append(msg.get("body", b""))

        await self.app(scope, receive, send_buffer)
        cuerpo = quitar_refresh(b"".join(partes)) if inicio.get("status") == 200 else b"".join(partes)
        await send({**inicio, "headers": _con_largo(inicio.get("headers", []), len(cuerpo))})
        await send({"type": "http.response.body", "body": cuerpo})
