"""Registro de visitas al sitio desde los asistentes (`visitas.py`): cuenta sin cookies ni IP y no escribe lo que llega crudo."""

import logging

from src.conector import visitas as V


def test_la_visita_responde_204_y_deja_una_linea_con_origen_y_pagina(servidor_http, caplog):
    c, _ = servidor_http
    with caplog.at_level(logging.INFO, logger="src.conector.visitas"):
        r = c.get(V.RUTA, params={"o": "claude", "p": "/agentika.html"})
    assert r.status_code == 204 and r.headers["cache-control"] == "no-store"
    lineas = [m.getMessage() for m in caplog.records if V.MARCA in m.getMessage()]
    assert lineas == [f"{V.MARCA} origen=claude pagina=/agentika.html"]


def test_lo_que_llega_de_afuera_se_limpia():
    assert V.normalizar("ChatGPT", "/agentika.html") == ("chatgpt", "/agentika.html")
    assert V.normalizar("hacker", None) == ("otro", "/")  # control: un origen desconocido no se escribe tal cual
    o, p = V.normalizar("claude", "/x?correo=a@b.com <script>")
    assert "@" not in p and "<" not in p and "?" not in p and len(p) <= 60
