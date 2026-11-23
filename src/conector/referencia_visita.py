"""Referencia cifrada en el enlace al sitio: une la visita al sitio con quién la hizo y qué buscó.

`buscar` agrega `&r=<referencia>` al enlace de la línea de fuente. La referencia es (invitado, hora de la búsqueda) cifrado con AES-GCM
y una llave derivada de `CONECTOR_FIRMA_SECRET`: quien la ve en la URL (el navegador, Analytics) no puede leerla ni fabricar una válida.
`/visita` la abre y anota la visita en `conector_llamada` junto al invitado; la consulta se encuentra por invitado y hora en
`conector_consulta`. Sin tabla nueva: no hace falta tocar la base con el rol dueño.

Solo para credenciales que aceptaron el aviso que dice que la visita se une a la búsqueda (`AVISO_MINIMO_VISITA`): el enlace va a
aientika.ai y eso lo declara el aviso v4.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import os
import re

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from src.conector.solicitud import clave

AVISO_MINIMO_VISITA = 4  # desde esta versión del aviso de privacidad el invitado sabe que la visita se une a la búsqueda
# La unión exige el aviso v4, que declara el enlace a aientika.ai. Las credenciales con un aviso anterior siguen funcionando, sin
# referencia en el enlace.
VIGENCIA_S = 7 * 86400  # una referencia más vieja no se une (un enlace guardado o reenviado semanas después)
_AAD = b"aientika-visita-v1"
_FORMA = re.compile(r"^[A-Za-z0-9_-]{40,160}$")
_INVITADO = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


def corresponde(aviso_version: int | None) -> bool:
    """¿La credencial aceptó un aviso que dice que la visita se une a la búsqueda?"""
    return aviso_version is not None and aviso_version >= AVISO_MINIMO_VISITA


def _llave() -> bytes:
    """32 bytes derivados de la clave de firma, separados de su uso para firmar tokens."""
    return hashlib.sha256(b"referencia-visita|" + clave().encode("utf-8")).digest()


def crear(invitado: str, ts: int) -> str:
    """La referencia opaca para el enlace: nonce de 12 bytes + texto cifrado, en base64 sin relleno."""
    nonce = os.urandom(12)
    cifrado = AESGCM(_llave()).encrypt(nonce, f"{invitado}|{int(ts)}".encode("utf-8"), _AAD)
    return base64.urlsafe_b64encode(nonce + cifrado).decode("ascii").rstrip("=")


def abrir(referencia: str | None, ahora: int) -> tuple[str, int] | None:
    """(invitado, hora de la búsqueda) o None si falta, está mal formada, fue alterada o venció. Nunca levanta."""
    if not referencia or not _FORMA.match(referencia):
        return None
    try:
        crudo = base64.urlsafe_b64decode(referencia + "=" * (-len(referencia) % 4))
        texto = AESGCM(_llave()).decrypt(crudo[:12], crudo[12:], _AAD).decode("utf-8")
        invitado, ts = texto.rsplit("|", 1)
        ts = int(ts)
    except (InvalidTag, ValueError, binascii.Error, UnicodeDecodeError, RuntimeError):
        return None
    if not _INVITADO.match(invitado) or not (0 <= ahora - ts <= VIGENCIA_S):
        return None
    return invitado, ts
