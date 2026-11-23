"""Invitados del conector: alta, baja y revocación. Identidad = código de invitado emitido por quien administra el servicio, sin cuenta de terceros.

El código se muestra UNA vez, al crearlo; en la base solo vive su sha256 (tiene ~80 bits de entropía, así que un hash sin sal alcanza y
permite buscar por él). El alfabeto excluye I, L, O, 0 y 1 para que se pueda dictar y escribir en el teléfono. Dar de baja a un
invitado revoca de inmediato todas sus credenciales: el siguiente request con su token da 401 y Claude le vuelve a pedir el código.
"""

from __future__ import annotations

import hashlib
import secrets

ALFABETO = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
LARGO = 16
GRUPO = 4


def generar_codigo() -> str:
    """Código nuevo `XXXX-XXXX-XXXX-XXXX` (criptográficamente aleatorio)."""
    c = "".join(secrets.choice(ALFABETO) for _ in range(LARGO))
    return "-".join(c[i:i + GRUPO] for i in range(0, LARGO, GRUPO))


def normalizar(codigo: str) -> str:
    """Mayúsculas y sin guiones ni espacios: el invitado puede escribirlo como quiera."""
    return "".join(ch for ch in codigo.upper() if ch.isalnum())


def hash_codigo(codigo: str) -> str:
    """sha256 del código normalizado: lo único que se guarda."""
    return hashlib.sha256(normalizar(codigo).encode("utf-8")).hexdigest()


ORIGENES = ("manual", "automatico")  # cómo se generó el código: a mano (script) o por un flujo automático


def alta(cur, etiqueta: str, ts: int, origen: str = "manual") -> tuple[str, str]:
    """Crea un invitado con su fecha (`creado_ts`) y `origen`. Devuelve (id, código en claro); el código no se recupera después."""
    if origen not in ORIGENES:
        raise ValueError(f"origen desconocido: {origen!r} (válidos: {', '.join(ORIGENES)})")
    id_, codigo = "inv-" + secrets.token_hex(4), generar_codigo()
    cur.execute("INSERT INTO invitado (id, codigo_sha256, etiqueta, activo, creado_ts, origen) VALUES (%s, %s, %s, %s, %s, %s)",
                (id_, hash_codigo(codigo), etiqueta[:80], True, ts, origen))
    return id_, codigo


def revocar_credenciales(cur, id_: str, ts: int, motivo: str) -> int:
    """Revoca todas las credenciales vigentes del invitado (cierra sus sesiones). Devuelve cuántas."""
    cur.execute("UPDATE credencial SET revocada_ts = %s, motivo = %s WHERE invitado_id = %s AND revocada_ts IS NULL",
                (ts, motivo, id_))
    return cur.rowcount


def baja(cur, id_: str, ts: int) -> bool:
    """Desactiva al invitado y revoca sus credenciales. False si no existe."""
    cur.execute("UPDATE invitado SET activo = %s, baja_ts = %s WHERE id = %s", (False, ts, id_))
    if cur.rowcount == 0:
        return False
    revocar_credenciales(cur, id_, ts, "baja del invitado")
    return True


def buscar_por_codigo(cur, codigo: str) -> str | None:
    """Id del invitado ACTIVO al que pertenece el código, o None. No distingue «no existe» de «dado de baja» (no se filtra cuál)."""
    cur.execute("SELECT id FROM invitado WHERE codigo_sha256 = %s AND activo = %s", (hash_codigo(codigo), True))
    fila = cur.fetchone()
    return fila[0] if fila else None


def etiqueta_activa(cur, id_: str) -> str | None:
    """La etiqueta del invitado si sigue activo; None si no existe o fue dado de baja (el «recordarme» cae con la baja)."""
    cur.execute("SELECT etiqueta FROM invitado WHERE id = %s AND activo = %s", (id_, True))
    fila = cur.fetchone()
    return fila[0] if fila else None


def normalizar_correo(correo: str) -> str:
    """Minúsculas y sin espacios: un correo, una persona, escrito como se escriba."""
    return correo.strip().lower()


def buscar_por_correo(cur, correo: str) -> str | None:
    """Id del invitado ACTIVO con ese correo, o None. No distingue «no existe» de «dado de baja» (no se filtra cuál)."""
    cur.execute("SELECT id FROM invitado WHERE correo = %s AND activo = %s", (normalizar_correo(correo), True))
    fila = cur.fetchone()
    return fila[0] if fila else None


def alta_por_correo(cur, correo: str, etiqueta: str, ts: int, origen: str = "manual") -> str:
    """Crea un invitado identificado por su correo, SIN código permanente. Devuelve su id.

    Necesita el esquema migrado (`codigo_sha256` nulable): en una base sin migrar falla en voz alta, no en silencio. El correo es único (índice).
    """
    if origen not in ORIGENES:
        raise ValueError(f"origen desconocido: {origen!r} (válidos: {', '.join(ORIGENES)})")
    id_ = "inv-" + secrets.token_hex(4)
    cur.execute("INSERT INTO invitado (id, codigo_sha256, etiqueta, activo, creado_ts, origen, correo) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (id_, None, etiqueta[:80], True, ts, origen, normalizar_correo(correo)))
    return id_


def listar(cur) -> list[tuple]:
    """(id, etiqueta, activo, credenciales vigentes, creado_ts, origen) de cada invitado; nunca el código ni su hash."""
    cur.execute("SELECT i.id, i.etiqueta, i.activo, (SELECT count(*) FROM credencial c WHERE c.invitado_id = i.id "
                "AND c.revocada_ts IS NULL), i.creado_ts, i.origen FROM invitado i ORDER BY i.creado_ts")
    return [tuple(f) for f in cur.fetchall()]
