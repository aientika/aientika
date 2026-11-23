# Copyright 2026 the Aientika contributors. Licensed under the Apache License, Version 2.0 (see LICENSE).
"""Qué clientes pueden registrarse en el OAuth del conector, y cómo se los nombra en pantalla.

Lista blanca de clientes OAuth: solo se aceptan los retornos de Claude y de ChatGPT. Pura, sin I/O: la usa `register_client` y se
prueba sola.

## Por qué la lista blanca es LA barrera

El registro dinámico (DCR) lo puede hacer cualquiera. Sin esta lista, un tercero registra un
cliente con SU `redirect_uri`, le manda al invitado un enlace de autorización legítimo de
este conector, el invitado pone su código, y el código de autorización —canjeable por una credencial
de 90 días sobre su cupo— viaja al servidor del tercero. PKCE no lo evita: el tercero es el
cliente, así que tiene su propio `code_verifier`.

El SDK compara el `redirect_uri` de `/authorize` por **igualdad exacta** contra lo registrado
(`mcp/shared/auth.py:118-125`). El comodín de puerto de localhost existe solo ACÁ, en el registro.

## Qué se acepta, exactamente

- `https://claude.ai/api/mcp/auth_callback` y `https://claude.com/api/mcp/auth_callback` (Anthropic
  avisa que puede migrar a la segunda): esquema, host y path idénticos; sin query, fragmento,
  usuario ni puerto.
- Retorno local de Claude Code y Claude Desktop: `http`, host `localhost`, `127.0.0.1` o `[::1]`,
  cualquier puerto, cualquier path, sin usuario ni fragmento.

- ChatGPT. Son los dos retornos que documenta OpenAI
  (developers.openai.com/apps-sdk/build/auth):
  - `https://chatgpt.com/connector_platform_oauth_redirect`, exacto;
  - `https://chatgpt.com/connector/oauth/<callback_id>`, con un solo segmento `[A-Za-z0-9_-]`.

  Mismas exigencias que Claude: https, sin puerto, usuario, query ni fragmento, y netloc igual al host. El riesgo que queda es
  el mismo que con claude.ai: un tercero con SU conector de ChatGPT recibe el código solo si el invitado escribe su código en
  un enlace que le mandó ese tercero. La pantalla muestra «ChatGPT (chatgpt.com)» para que el invitado vea a quién autoriza.

Todas las URIs de un registro tienen que pasar: una buena al lado de una mala no alcanza.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

_RETORNOS_CLAUDE_WEB = {
    ("claude.ai", "/api/mcp/auth_callback"),
    ("claude.com", "/api/mcp/auth_callback"),
}
_RETORNO_CHATGPT_EXACTO = ("chatgpt.com", "/connector_platform_oauth_redirect")
_RETORNO_CHATGPT_CALLBACK = re.compile(r"/connector/oauth/[A-Za-z0-9_-]{1,128}")
_HOSTS_LOCALES = {"localhost", "127.0.0.1", "::1"}

ETIQUETA_WEB = "Claude (claude.ai)"
ETIQUETA_CHATGPT = "ChatGPT (chatgpt.com)"
ETIQUETA_LOCAL = "Claude en este equipo (Claude Code o Desktop)"


def _https_limpia(uri: str):
    """Partes de la URI si es https sin puerto, usuario, query ni fragmento, y con netloc igual al host; si no, None."""
    try:
        p = urlsplit(uri)
        puerto = p.port
    except ValueError:
        return None
    ok = (p.scheme == "https" and puerto is None and not p.username and not p.password and not p.query and not p.fragment
          and p.netloc == p.hostname)
    return p if ok else None


def es_retorno_chatgpt(uri: str) -> bool:
    """True si es uno de los dos retornos de OAuth de ChatGPT, con las mismas exigencias que el de claude.ai."""
    p = _https_limpia(uri)
    if p is None or p.hostname != "chatgpt.com":
        return False
    return (p.hostname, p.path) == _RETORNO_CHATGPT_EXACTO or bool(_RETORNO_CHATGPT_CALLBACK.fullmatch(p.path))


def es_retorno_web(uri: str) -> bool:
    """True si es el retorno de claude.ai / claude.com, con igualdad estricta."""
    try:
        p = urlsplit(uri)
        puerto = p.port
    except ValueError:
        return False
    return (
        p.scheme == "https"
        and puerto is None
        and not p.username
        and not p.password
        and not p.query
        and not p.fragment
        and (p.hostname or "", p.path) in _RETORNOS_CLAUDE_WEB
        # `hostname` baja a minúsculas y quita el usuario: se exige además que el netloc sea
        # EXACTAMENTE el host, así `claude.ai@evil.com` no llega nunca a compararse.
        and p.netloc == p.hostname
    )


def es_retorno_local(uri: str) -> bool:
    """True si es un retorno http a esta misma máquina, en cualquier puerto."""
    try:
        p = urlsplit(uri)
        p.port  # noqa: B018 - valida que el puerto sea numerico
    except ValueError:
        return False
    return (
        p.scheme == "http"
        and not p.username
        and not p.password
        and not p.fragment
        and (p.hostname or "") in _HOSTS_LOCALES
    )


def tipo_retorno(uri: str) -> str:
    """«claude», «chatgpt» o «local»: decide qué aviso muestra la pantalla (el de Desktop solo para el retorno local)."""
    if es_retorno_web(uri):
        return "claude"
    return "chatgpt" if es_retorno_chatgpt(uri) else "local"


def redirect_uris_validas(uris: list[str]) -> bool:
    """Todas tienen que pasar, y tiene que haber al menos una."""
    return bool(uris) and all(es_retorno_web(u) or es_retorno_chatgpt(u) or es_retorno_local(u) for u in uris)


def etiqueta_de(uris: list[str]) -> str:
    """Lo que ve el usuario en la pantalla de autorización. NUNCA el `client_name` declarado."""
    if any(es_retorno_chatgpt(u) for u in uris):
        return ETIQUETA_CHATGPT
    return ETIQUETA_WEB if any(es_retorno_web(u) for u in uris) else ETIQUETA_LOCAL
