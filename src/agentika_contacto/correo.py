"""Envío de correos de contacto (códigos de acceso y bienvenida) por un servicio con dominio propio. Mientras no estén
`CORREO_API_KEY` (variable de entorno) y `CORREO_REMITENTE`, no se envía nada y se dice por qué (un correo que no salió nunca se
da por enviado). Servicio: Resend.

La petición sale con `User-Agent: agent`: solo la clave y el remitente propios. El destinatario no se escribe en los logs.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from dataclasses import dataclass

URL_RESEND = "https://api.resend.com/emails"
_registro = logging.getLogger(__name__)


@dataclass(frozen=True)
class Envio:
    """Resultado de un envío: `enviado`, o el `motivo` en palabras de por qué no."""

    enviado: bool
    motivo: str | None = None


def configurado() -> bool:
    """¿Hay clave y remitente? Sin los dos, el correo está apagado (hoy: falta el dominio)."""
    return bool(os.environ.get("CORREO_API_KEY", "").strip() and os.environ.get("CORREO_REMITENTE", "").strip())


def enviar(destino: str, asunto: str, texto: str, abrir=urllib.request.urlopen) -> Envio:
    """Manda un correo de texto plano. Nunca levanta: devuelve Envio(False, motivo) si no hay configuración o el servicio falla."""
    if not configurado():
        return Envio(False, "el correo todavía no está configurado (falta el dominio y el servicio de envío)")
    cuerpo = json.dumps({"from": os.environ["CORREO_REMITENTE"], "to": [destino], "subject": asunto, "text": texto}).encode("utf-8")
    pedido = urllib.request.Request(URL_RESEND, data=cuerpo, method="POST", headers={
        "Authorization": f"Bearer {os.environ['CORREO_API_KEY']}", "Content-Type": "application/json", "User-Agent": "agent"})
    try:
        with abrir(pedido, timeout=20) as r:
            ok = 200 <= r.status < 300 and "id" in json.loads(r.read().decode("utf-8", errors="replace") or "{}")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        _registro.warning("correo: falló el envío (%s)", type(exc).__name__)
        return Envio(False, "no pudimos mandar el correo ahora; probá en unos minutos")
    return Envio(True) if ok else Envio(False, "el servicio de correo no confirmó el envío")
