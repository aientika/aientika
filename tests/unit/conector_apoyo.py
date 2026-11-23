"""Apoyo común de los tests del conector (servidor, OAuth, límites): la base de ESTADO es SQLite con el DDL real de producción.

El SQL de `limites`, `oauth`, `registro` y `presupuesto_voyage` está escrito en el subconjunto común de Postgres y SQLite, así que estos
tests ejecutan las mismas sentencias que correrán en producción (UPSERT condicional, canje atómico). Lo que SQLite no prueba: bloqueo de
filas de Postgres bajo concurrencia real y los tipos de pg8000; eso queda para las pruebas manuales contra el entorno real.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import pytest

from src.conector import bd, esquema_conector

CR = timezone(timedelta(hours=-6))


def cr(texto: str) -> datetime:
    """Instante en hora de Costa Rica desde 'AAAA-MM-DD HH:MM'."""
    return datetime.strptime(texto, "%Y-%m-%d %H:%M").replace(tzinfo=CR)


def volcar_tablas(ruta: str) -> str:
    """Todo el contenido de la base de estado como texto (para buscar una frase que no debe estar)."""
    conn = bd.fabrica_sqlite(ruta)()
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    salida = []
    for (tabla,) in cur.fetchall():
        c2 = conn.cursor()
        c2.execute(f"SELECT * FROM {tabla}")
        salida.append(f"{tabla}: {c2.fetchall()}")
    conn.close()
    return "\n".join(salida)


@pytest.fixture
def estado_sqlite(tmp_path):
    """Base de estado de prueba con el esquema del conector; devuelve la ruta del archivo."""
    ruta = str(tmp_path / "estado.db")
    fabrica = bd.fabrica_sqlite(ruta)
    esquema_conector.crear_esquema(fabrica())
    bd.usar(estado=fabrica, lectura=lambda: (_ for _ in ()).throw(AssertionError("la prueba no debía leer la base")))
    yield ruta
    bd.usar()


@pytest.fixture
def logs():
    """Captura TODO lo que se loguee, a nivel DEBUG en la raíz (incluye el SDK de MCP), como texto."""
    registros: list[str] = []

    class Colector(logging.Handler):
        def emit(self, record):
            registros.append(self.format(record))

    raiz, h = logging.getLogger(), Colector()
    h.setFormatter(logging.Formatter("%(name)s %(levelname)s %(message)s"))
    previo = raiz.level
    raiz.addHandler(h)
    raiz.setLevel(logging.DEBUG)
    yield registros
    raiz.removeHandler(h)
    raiz.setLevel(previo)


# --- servidor completo con OAuth, por HTTP (lo que se prueba es el RESULTADO: qué pasa en el request siguiente) -----------

URL = "https://conector.test"
CALLBACK = "https://claude.ai/api/mcp/auth_callback"


def retorno(resp) -> str:
    """URL de vuelta al asistente tras autorizar: el `Location` del 303 (Desktop, cancelar) o el botón «Volver» de la pantalla «Listo»
    (Claude y ChatGPT web, pantalla_listo.py). Cadena vacía si la respuesta no devuelve al asistente."""
    import html as _html
    if resp.status_code == 303:
        return resp.headers["location"]
    m = resp.status_code == 200 and "id='volver'" in resp.text and resp.text.split("id='volver' class='boton' href='")[1].split("'")[0]
    return _html.unescape(m) if m else ""


@pytest.fixture
def servidor_http(estado_sqlite, monkeypatch):
    """(cliente HTTP, ruta de la base de estado). Dentro de horario aunque la prueba corra de noche; la base de fallos está 'caída'."""
    from starlette.testclient import TestClient

    from src.conector import limites
    from src.conector.herramientas import Herramientas
    from src.conector.servidor import Configuracion, construir

    monkeypatch.setenv("CONECTOR_FIRMA_SECRET", "s" * 48)
    monkeypatch.setattr(limites, "fuera_de_horario", lambda ahora: False)
    bd.usar(estado=bd.fabrica_sqlite(estado_sqlite), lectura=lambda: (_ for _ in ()).throw(OSError("la base no responde")))
    _, app = construir(Configuracion(url_publica=URL), Herramientas())
    with TestClient(app, base_url=URL, follow_redirects=False) as c:
        yield c, estado_sqlite


def registrar_cliente(c, uris=(CALLBACK,), grants=("authorization_code",)):
    """POST /register como lo haría Claude; devuelve la respuesta."""
    return c.post("/register", json={"redirect_uris": list(uris), "client_name": "Claude", "grant_types": list(grants),
                                     "response_types": ["code"], "token_endpoint_auth_method": "none"})


def pkce():
    """(verifier, challenge S256)."""
    import base64
    import hashlib
    import secrets
    v = secrets.token_urlsafe(48)
    return v, base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).rstrip(b"=").decode()


def invitar(etiqueta="Colega de prueba"):
    """Alta de un invitado en la base de estado; devuelve (id, código en claro)."""
    from src.conector import invitados
    with bd.estado() as conn:
        return invitados.alta(conn.cursor(), etiqueta, 1000)
