"""Correo del invitado y su autorización de contacto. Guardar, dar de baja y listar no dependen del servicio de envío.

La autorización es opcional, nace en «no» y se guarda con la fecha y la versión del texto que la persona vio, igual que el aviso.
El correo no aparece en los logs ni se entrega a terceros; `promociones` lista solo a quienes aceptaron y siguen activos.
"""

from __future__ import annotations

import re

# Texto de la casilla (versión 1). Si cambia, se sube la versión y no se edita en silencio.
TEXTO_PROMOCIONES = "Acepto recibir por correo novedades, promociones y servicios adicionales de Agéntika."
VERSION_PROMOCIONES = 1
_CORREO = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$")


def normalizar_correo(correo: str) -> str:
    """Minúsculas y sin espacios; levanta ValueError si no tiene forma de correo (no se guarda cualquier cosa)."""
    c = (correo or "").strip().lower()
    if not _CORREO.match(c) or len(c) > 120:
        raise ValueError("el correo no tiene una forma válida")
    return c


def guardar(cur, invitado: str, correo: str | None, acepta: bool, ts: int) -> bool:
    """Guarda el correo (si viene) y la autorización con fecha y versión. False si el invitado no existe."""
    if correo is not None:
        c = normalizar_correo(correo)
        # Un correo, una persona (la columna no tiene índice único en las bases migradas: se controla acá).
        cur.execute("SELECT id FROM invitado WHERE correo = %s AND id <> %s", (c, invitado))
        if cur.fetchone():
            raise ValueError("ese correo ya está registrado para otro invitado")
        cur.execute("UPDATE invitado SET correo = %s WHERE id = %s", (c, invitado))
        if cur.rowcount == 0:
            return False
    cur.execute("UPDATE invitado SET acepta_promociones = %s, promociones_ts = %s, promociones_version = %s WHERE id = %s",
                (bool(acepta), ts, VERSION_PROMOCIONES, invitado))
    return cur.rowcount > 0


def dar_de_baja(cur, correo: str, ts: int) -> bool:
    """La persona deja de recibir promociones (enlace de baja de cada correo). False si el correo no está."""
    cur.execute("UPDATE invitado SET acepta_promociones = %s, promociones_ts = %s WHERE correo = %s",
                (False, ts, normalizar_correo(correo)))
    return cur.rowcount > 0


def promociones(cur) -> list[tuple[str, str, str]]:
    """(id, etiqueta, correo) de los invitados activos que aceptaron recibir promociones; nunca los que no."""
    cur.execute("SELECT id, etiqueta, correo FROM invitado WHERE activo = %s AND acepta_promociones = %s AND correo IS NOT NULL "
                "ORDER BY creado_ts", (True, True))
    return [tuple(f) for f in cur.fetchall()]
