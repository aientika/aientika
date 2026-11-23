"""Prueba de tarjeta visual `visitar_sitio`: la herramienta apunta a la interfaz y el recurso la sirve."""

import asyncio
import os

from src.conector import tarjeta_sitio as T
from src.conector.herramientas import Herramientas
from src.conector.servidor import Configuracion, construir

URL = "https://aientika-conector-000000000000.us-east1.run.app"


def _servidor():
    os.environ.setdefault("CONECTOR_FIRMA_SECRET", "k" * 48)
    return construir(Configuracion(url_publica=URL), Herramientas())[0]


def test_la_herramienta_apunta_a_la_tarjeta_por_mcp_apps_y_por_chatgpt():
    tools = {t.name: t for t in asyncio.run(_servidor().list_tools())}
    meta = tools["aientika_visitar_sitio"].meta
    assert meta["ui"]["resourceUri"] == T.URI and meta["openai/outputTemplate"] == T.URI
    assert tools["aientika_visitar_sitio"].annotations.readOnlyHint is True


def test_el_recurso_sirve_el_html_con_el_mime_de_mcp_apps():
    srv = _servidor()
    recursos = {str(r.uri): r for r in asyncio.run(srv.list_resources())}
    assert recursos[T.URI].mimeType == T.MIME
    contenido = list(asyncio.run(srv.read_resource(T.URI)))[0]
    assert "Visitar el sitio" in contenido.content and T.SITIO in contenido.content and "ui/open-link" in contenido.content


def test_el_enlace_marca_el_origen_segun_el_cliente():
    assert "utm_source=claude" in T.enlace("Claude-User")
    assert "utm_source=chatgpt" in T.enlace("openai-mcp/1.0.0")
    assert "utm_source=otro" in T.enlace(None)  # control: sin cliente no se inventa el origen
    r = T.resultado("Claude-User")
    assert r["enlace"] in r["mensaje"] and r["enlace"].startswith(T.SITIO)
