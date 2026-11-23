"""Estructura del conector: OAuth fuera de horario o con la base caída, los INFO del conector llegan a stdout
con el logging de producción, y el aviso de Desktop en la pantalla de acceso.

Con la base apagada, `/register` y `/authorize` daban 500.
Cada detector con su control: en horario y con la base viva `/register` sigue dando 201, y una falla que NO es de la base sigue
siendo un 500 (no se disfraza un error nuestro de «no disponible»).
"""

import io
import logging
from urllib.parse import parse_qs, urlsplit

import pytest
from conector_apoyo import CALLBACK, URL, pkce, registrar_cliente, volcar_tablas
from test_conector_oauth import canjear, flujo_completo, initialize
from test_conector_servidor import FRASE_MARCADA, mcp

from src.conector import bd, limites, oauth
from src.conector.asgi import ERROR_NO_DISPONIBLE

LOCAL = "http://localhost:51234/callback"


def caida():
    raise OSError("VM apagada")


def pedir_rutas_oauth(c, cid="cliente-x"):
    """Las cuatro rutas del servidor de autorización que tocan la base, como las llama Claude."""
    return {
        "/register": registrar_cliente(c),
        "/authorize": c.get("/authorize", params={"response_type": "code", "client_id": cid, "redirect_uri": CALLBACK,
                                                  "code_challenge": pkce()[1], "code_challenge_method": "S256", "state": "s",
                                                  "resource": URL + "/mcp"}),
        "/token": canjear(c, cid, "codigo-x", pkce()[0]),
        "/revoke": c.post("/revoke", data={"token": "x", "client_id": cid, "client_secret": ""}),
    }


def es_503_oauth(r, mensaje: str) -> bool:
    cuerpo = r.json()
    return (r.status_code == 503 and cuerpo["error"] == ERROR_NO_DISPONIBLE and cuerpo["error_description"] == mensaje
            and r.headers["cache-control"] == "no-store")


# --- OAuth fuera de horario ------------------------------------------------------------------------------------------------------------------

def test_fuera_de_horario_las_rutas_oauth_dan_503_con_el_horario_sin_tocar_la_base(servidor_http, monkeypatch):
    c, ruta = servidor_http
    antes = volcar_tablas(ruta)
    monkeypatch.setattr(limites, "fuera_de_horario", lambda ahora: True)
    for nombre, r in pedir_rutas_oauth(c).items():
        assert es_503_oauth(r, limites.MENSAJE_FUERA_DE_HORARIO), (nombre, r.status_code, r.text)
        assert "7:00 a 23:00" in r.json()["error_description"]
    assert volcar_tablas(ruta) == antes
    assert c.get("/.well-known/oauth-authorization-server").status_code == 200  # los metadatos no tocan la base: siguen


def test_con_la_base_caida_en_horario_las_rutas_oauth_dan_503_en_palabras(servidor_http):
    c, _ = servidor_http
    cid = registrar_cliente(c).json()["client_id"]  # registrado con la base viva, para que /authorize y /token lleguen a leerla
    bd.usar(estado=caida, lectura=caida)
    for nombre, r in pedir_rutas_oauth(c, cid).items():
        if nombre == "/revoke":  # un token que no es JWT se descarta antes de abrir la base: el SDK contesta 200 sin tocarla
            continue
        assert es_503_oauth(r, bd.MENSAJE_NO_DISPONIBLE), (nombre, r.status_code, r.text)


def test_revoke_con_un_token_valido_y_la_base_caida_da_503(servidor_http):
    c, _ = servidor_http
    token, cid, *_ = flujo_completo(c)
    bd.usar(estado=caida, lectura=caida)
    r = c.post("/revoke", data={"token": token, "client_id": cid, "client_secret": ""})
    assert es_503_oauth(r, bd.MENSAJE_NO_DISPONIBLE), (r.status_code, r.text)


def test_la_caida_de_la_base_se_reconoce_tambien_dentro_de_un_grupo_de_excepciones():
    import builtins

    from src.conector.asgi import _cae_la_base
    grupo = builtins.BaseExceptionGroup  # ruff sin target-version no conoce el builtin de 3.11
    assert _cae_la_base(grupo("anyio", [ValueError("a"), bd.BDNoDisponible("OSError")]))
    assert not _cae_la_base(grupo("anyio", [ValueError("a")])) and not _cae_la_base(ValueError("b"))


def test_control_positivo_en_horario_y_con_la_base_viva_el_registro_da_201(servidor_http):
    c, _ = servidor_http
    r = registrar_cliente(c)
    assert r.status_code == 201 and r.json()["client_id"]
    meta = c.get("/.well-known/oauth-authorization-server").json()
    assert meta["grant_types_supported"] == ["authorization_code"]


def test_una_falla_que_no_es_de_la_base_sigue_siendo_500(estado_sqlite, monkeypatch):
    from starlette.testclient import TestClient

    from src.conector.herramientas import Herramientas
    from src.conector.servidor import Configuracion, construir
    monkeypatch.setenv("CONECTOR_FIRMA_SECRET", "s" * 48)
    monkeypatch.setattr(limites, "fuera_de_horario", lambda ahora: False)
    monkeypatch.setattr(oauth.ProveedorConector, "_registrar", lambda *a: (_ for _ in ()).throw(ValueError("defecto nuestro")))
    _, app = construir(Configuracion(url_publica=URL), Herramientas())
    with TestClient(app, base_url=URL, raise_server_exceptions=False) as c:
        assert registrar_cliente(c).status_code == 500


def test_en_modo_sin_auth_no_hay_rutas_oauth_aunque_sea_de_noche(monkeypatch):
    from starlette.testclient import TestClient

    from src.conector.herramientas import Herramientas
    from src.conector.servidor import Configuracion, construir
    monkeypatch.setattr(limites, "fuera_de_horario", lambda ahora: True)
    _, app = construir(Configuracion(url_publica="http://localhost:8080", sin_auth=True), Herramientas())
    with TestClient(app, base_url="http://localhost:8080") as c:
        assert c.post("/register", json={}).status_code == 404


# --- Logging a stdout ------------------------------------------------------------------------------------------------------------------

@pytest.fixture
def niveles_intactos():
    """Restaura niveles y handlers de los loggers que toca `configurar_logging`."""
    nombres = ("", "src.conector", "mcp")
    previos = {n: logging.getLogger(n).level for n in nombres}
    handlers = list(logging.getLogger().handlers)
    yield
    for n, nivel in previos.items():
        logging.getLogger(n).setLevel(nivel)
    raiz = logging.getLogger()
    for h in list(raiz.handlers):
        if h not in handlers:
            raiz.removeHandler(h)


def test_con_el_logging_de_produccion_llegan_los_info_del_oauth_y_no_la_consulta(servidor_http, niveles_intactos):
    from src.conector.servidor import configurar_logging
    c, _ = servidor_http
    raiz = logging.getLogger()

    # Control negativo: sin configurar (raíz en WARNING, el default de Python), «autorizado» no llega a ninguna salida.
    crudo = io.StringIO()
    raiz.addHandler(logging.StreamHandler(crudo))
    raiz.setLevel(logging.WARNING)
    logging.getLogger("src.conector").setLevel(logging.NOTSET)
    flujo_completo(c)
    assert "autorizado" not in crudo.getvalue()

    salida = io.StringIO()
    configurar_logging(salida)
    token, cid, code, _ = flujo_completo(c)
    mcp(c, token, "tools/call", {"name": "aientika_buscar_jurisprudencia_cr", "arguments": {"consulta": f"culpa {FRASE_MARCADA}"}})
    assert initialize(c, token[:-3] + ("AAA" if not token.endswith("AAA") else "BBB")).status_code == 401
    assert c.post("/revoke", data={"token": token, "client_id": cid, "client_secret": ""}).status_code == 200
    assert initialize(c, token).status_code == 401
    texto = salida.getvalue()
    for linea in ("[conector-oauth] codigo emitido cliente=" + cid[:8], "[conector-oauth] autorizado jti=",
                  "[conector-oauth] revocada por /revoke", "[conector] token rechazado: firma o vencimiento",
                  "[conector] token rechazado: revocado"):
        assert linea in texto, (linea, texto)
    assert cid not in texto and code not in texto and token not in texto  # client_id truncado; ni el código ni el token
    assert FRASE_MARCADA not in texto  #
    assert logging.getLogger("mcp").level == logging.WARNING and raiz.level == logging.WARNING


# --- Aviso de Desktop ------------------------------------------------------------------------------------------------------------------

def pantalla_para(c, retorno: str) -> str:
    cid = registrar_cliente(c, uris=[retorno]).json()["client_id"]
    r = c.get("/authorize", params={"response_type": "code", "client_id": cid, "redirect_uri": retorno, "code_challenge": pkce()[1],
                                    "code_challenge_method": "S256", "state": "st", "resource": URL + "/mcp"})
    assert parse_qs(urlsplit(r.headers["location"]).query)["s"], r.text
    return c.get(r.headers["location"]).text


def test_la_pantalla_avisa_el_plazo_de_desktop_solo_con_retorno_local(servidor_http):
    import html

    from src.conector.pantalla import AVISO_DESKTOP
    c, _ = servidor_http
    assert html.escape(AVISO_DESKTOP) in pantalla_para(c, LOCAL)
    assert html.escape(AVISO_DESKTOP) not in pantalla_para(c, CALLBACK)  # control: en Claude web no se muestra
