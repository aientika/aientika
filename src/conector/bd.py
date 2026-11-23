"""Capa delgada de acceso a Postgres del conector, INYECTABLE: en producción es pg8000 contra el host privado de la base; en las
pruebas y en el modo de desarrollo se reemplaza por fábricas falsas (`usar`), sin tocar el resto del código.

Hay dos conexiones con propósitos distintos: `lectura` (la base de fallos: sesión de solo lectura, nada se escribe ahí) y
`estado` (las tablas del conector: invitados, OAuth, contadores). En producción son la misma base. La conexión nunca se queda
colgada si la base está apagada: el connect tiene tope corto y todo error de conexión sube como `BDNoDisponible`, que las
herramientas traducen a palabras (nunca a «cero resultados»). El texto de una excepción no se vuelca a los logs: un error de
`tsquery` de Postgres repite la consulta del usuario.
"""

from __future__ import annotations

import contextlib
import logging
import os
import sqlite3
from datetime import datetime, timezone

TIEMPO_CONEXION_S = 8
TIEMPO_CONSULTA_S = 60
MENSAJE_NO_DISPONIBLE = "El servicio no pudo responder ahora. Probá de nuevo en unos minutos."
# Línea de log estable: una caída en horario no debe pasar inadvertida. Si se cambia el texto, hay que ajustar también
# cualquier filtro de logs que la busque.
AVISO_EN_HORARIO = "[conector-bd] base no disponible en horario"
_log = logging.getLogger(__name__)


class BDNoDisponible(RuntimeError):
    """No se pudo abrir la conexión (base apagada, red, contraseña): se dice en palabras, no se devuelve vacío."""


_fabricas: dict = {"estado": None, "lectura": None}


def usar(estado=None, lectura=None) -> None:
    """Reemplaza las fábricas de conexión (pruebas y desarrollo). `None` deja la de producción para esa conexión."""
    _fabricas["estado"], _fabricas["lectura"] = estado, lectura


def _postgres():
    """pg8000 contra el host privado de la base (`REPLICA_DB_HOST`) o, desde el equipo de desarrollo, el conector de la instancia."""
    import pg8000.dbapi
    if os.environ.get("REPLICA_DB_INSTANCIA") or os.environ.get("REPLICA_DB_SOCKET"):
        from src.indice.postgres import conectar
        return conectar()
    conn = pg8000.dbapi.connect(host=os.environ["REPLICA_DB_HOST"], port=int(os.environ.get("REPLICA_DB_PORT", "5432")),
                                database=os.environ.get("REPLICA_DB_NAME", "replica"), user=os.environ["REPLICA_DB_USER"],
                                password=os.environ["REPLICA_DB_PASSWORD"], timeout=TIEMPO_CONEXION_S, ssl_context=contexto_tls())
    with contextlib.suppress(Exception):  # el tope corto era para conectar; las consultas pueden tardar más
        conn._usock.settimeout(TIEMPO_CONSULTA_S)
    return conn


def contexto_tls():
    """TLS hacia la base si está `REPLICA_DB_CA` (el PEM de la CA de la instancia, que no es secreto): verifica el certificado
    contra esa CA. No compara el nombre: el certificado no trae la IP privada. Sin la variable, sin TLS (despliegues sin cifrado y
    pruebas). La instancia exige cifrado, así que olvidar la variable falla ruidoso, no en claro."""
    ca = os.environ.get("REPLICA_DB_CA")
    if not ca:
        return None
    import ssl
    ctx = ssl.create_default_context(cadata=ca)
    ctx.check_hostname = False  # la verificación de la cadena (CERT_REQUIRED) sigue activa
    # Sin el modo estricto de Python >= 3.13: los certificados de la instancia no traen Authority Key Identifier y, con la CA correcta,
    # daban «Missing Authority Key Identifier». La firma, la vigencia y la CA se siguen
    # verificando; lo prueba test_conector_bd_aviso_caida con un apretón de manos real y una CA ajena.
    ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
    return ctx


def _abrir(clave: str):
    fabrica = _fabricas[clave] or _postgres
    try:
        return fabrica()
    except KeyError as exc:  # variable de entorno que falta: configuración, no caída de la base, pero para el usuario es lo mismo
        _avisar_caida(f"falta configurar {exc.args[0]}")
        raise BDNoDisponible(f"falta configurar {exc.args[0]}") from None
    except Exception as exc:
        _avisar_caida(type(exc).__name__)
        raise BDNoDisponible(type(exc).__name__) from None


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _avisar_caida(tipo: str) -> None:
    """En horario, una conexión que falla es una caída y se registra para la alerta; fuera de horario la base está apagada a propósito.
    Solo el tipo de la excepción: su texto puede repetir datos de la consulta."""
    from src.conector import limites  # aquí y no arriba: limites importa bd
    if not limites.fuera_de_horario(_ahora()):
        _log.warning("%s: %s", AVISO_EN_HORARIO, tipo)


def conectar_lectura():
    """Conexión de solo lectura a la base de fallos. El que llama la cierra."""
    conn = _abrir("lectura")
    try:
        cur = conn.cursor()
        cur.execute("SET default_transaction_read_only = on")
        conn.commit()
    except Exception:  # un fake o SQLite no entiende el SET: la protección real es la de Postgres
        with contextlib.suppress(Exception):
            conn.rollback()
    return conn


@contextlib.contextmanager
def estado():
    """Transacción sobre las tablas del conector: commit al salir bien, rollback si algo falla, siempre se cierra."""
    conn = _abrir("estado")
    try:
        yield conn
        conn.commit()
    except BaseException:
        with contextlib.suppress(Exception):
            conn.rollback()
        raise
    finally:
        with contextlib.suppress(Exception):
            conn.close()


class _CursorSqlite:
    """Cursor de SQLite que acepta los marcadores `%s` de pg8000 (solo para pruebas y desarrollo)."""

    def __init__(self, cur):
        self._cur = cur

    def execute(self, sql, params=()):
        self._cur.execute(sql.replace("%s", "?"), tuple(params))
        return self

    def __getattr__(self, nombre):
        return getattr(self._cur, nombre)

    def __iter__(self):
        return iter(self._cur)


class _ConexionSqlite:
    def __init__(self, ruta):
        self._c = sqlite3.connect(ruta, timeout=30, check_same_thread=False)

    def cursor(self):
        return _CursorSqlite(self._c.cursor())

    def __getattr__(self, nombre):
        return getattr(self._c, nombre)


def es_sqlite(conn) -> bool:
    """¿Es la conexión de pruebas/desarrollo? Lo usa el script de esquema: las `MIGRACIONES` (ADD COLUMN IF NOT EXISTS) son de Postgres."""
    return isinstance(conn, _ConexionSqlite)


def fabrica_sqlite(ruta: str):
    """Fábrica de conexiones SQLite con la misma interfaz que pg8000 para lo que usa el conector (no existe en producción)."""
    return lambda: _ConexionSqlite(ruta)
