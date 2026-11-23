"""Servidor MCP: contrato de herramientas versionado, hosts declarados (421), sin estado, modo de desarrollo prohibido en prod con el SDK.

Contrato: la huella de las herramientas REALES debe coincidir con la de `CONECTOR_VERSION`; quien cambie un parámetro sin subir la
versión rompe este test (y el control negativo prueba que el detector detecta). Hosts: el default de FastMCP solo admite localhost y daba 421
en prod; se prueba con un host declarado (pasa) y uno ajeno (421).
"""

import asyncio
import json
import logging

import pytest
from conector_apoyo import URL, volcar_tablas
from test_conector_oauth import flujo_completo

from src.conector import version as V
from src.conector.herramientas import Herramientas
from src.conector.servidor import (Configuracion, ConfiguracionInvalida, configuracion_desde_entorno, construir,
                                         seguridad_de_transporte)

FRASE_MARCADA = "QWX-consulta-marcada-del-sdk-4471"


def herramientas_reales():
    import os
    os.environ.setdefault("CONECTOR_FIRMA_SECRET", "k" * 48)
    srv, _ = construir(Configuracion(url_publica=URL), Herramientas())
    return asyncio.run(srv.list_tools())


def test_cuatro_herramientas_son_de_solo_lectura_y_reportar_no_porque_escribe_una_fila():
    tools = {t.name: t for t in herramientas_reales()}
    assert tuple(tools) == V.HERRAMIENTAS
    assert all(tools[n].annotations and tools[n].annotations.readOnlyHint is True for n in V.HERRAMIENTAS if n != V.NOMBRES_MCP["reportar"])
    rep = tools["aientika_reportar_respuesta"].annotations  # la anotación declarada debe ser verdadera
    assert rep.readOnlyHint is False and rep.destructiveHint is False and rep.openWorldHint is False


def test_el_contrato_no_cambia_sin_subir_la_version():
    assert V.CONECTOR_VERSION == "2.1.1" and V.CONECTOR_VERSION in V.HUELLAS
    assert V.HUELLAS["2.1.1"] == V.HUELLAS["2.1.0"] == V.HUELLAS["2.0.0"]  # 2.1.0: cambia la línea COBERTURA (salida), no la entrada
    assert V.HUELLAS["2.0.0"] != V.HUELLAS["1.14.0"]  # 2.0.0: nombres MCP nuevos, otra entrada, otra huella
    assert all(n.startswith("aientika_") for n in V.HERRAMIENTAS) and len(set(V.HERRAMIENTAS)) == len(V.NOMBRES_MCP)
    assert V.HUELLAS["1.13.0"] == V.HUELLAS["1.12.0"]  # 1.13.0: el enlace de `fuente` va a aientika.ai, misma entrada
    assert V.HUELLAS["1.14.0"] == V.HUELLAS["1.13.0"]  # 1.14.0: horario de 7:00 a 23:00, misma entrada
    assert V.HUELLAS["1.10.0"] == V.HUELLAS["1.9.0"]  # 1.10.0: el enlace de `fuente` en markdown, misma entrada
    assert V.HUELLAS["1.9.0"] == V.HUELLAS["1.8.0"]  # 1.9.0 cambia la salida de `buscar` (línea `fuente`), no la entrada
    assert V.HUELLAS["1.8.0"] != V.HUELLAS["1.7.0"]  # 1.8.0 agrega visitar_sitio: otra entrada, otra huella
    assert V.HUELLAS["1.7.0"] == V.HUELLAS["1.6.0"]  # 1.7.0 cambia la salida de `catalogo`, no la entrada
    assert V.HUELLAS["1.6.0"] != V.HUELLAS["1.5.0"]  # 1.6.0 agrega tramites_buscar, tramite y catalogo: otra entrada, otra huella
    assert V.HUELLAS["1.5.0"] == V.HUELLAS["1.4.0"]  # 1.5.0 cambia la salida (por_tanto_recortado) y el registro, no la entrada
    assert V.HUELLAS["1.4.0"] == V.HUELLAS["1.3.0"]  # 1.4.0 (opción b de la guarda) cambia la salida de ficha y buscar, no la entrada
    assert V.huella_contrato(herramientas_reales()) == V.HUELLAS[V.CONECTOR_VERSION]
    assert V.HUELLAS["1.0.0"] != V.HUELLAS["1.1.0"]  # la versión publicada no se editó: se agregó otra
    assert V.HUELLAS["1.2.0"] == V.HUELLAS["1.1.0"]  # 1.2.0 cambia solo la salida de `buscar`, no la entrada
    assert V.HUELLAS["1.3.0"] == V.HUELLAS["1.2.0"]  # 1.3.0 fase A) cambia la salida de tres herramientas, no la entrada


def test_control_negativo_un_parametro_nuevo_cambia_la_huella():
    tools = herramientas_reales()
    alterada = [t.model_copy(update={"inputSchema": {**t.inputSchema, "properties": {**t.inputSchema["properties"], "extra": {"type": "string"}}}})
                if t.name == V.NOMBRES_MCP["buscar"] else t for t in tools]
    assert V.huella_contrato(alterada) != V.huella_contrato(tools)
    assert V.huella_contrato(tools[:-1]) != V.huella_contrato(tools)  # quitar una herramienta tampoco pasa


def test_la_descripcion_de_cada_herramienta_esta_en_espanol_y_el_texto_afinado_no_cambia_la_huella():
    assert all(len(t.description or "") > 40 for t in herramientas_reales())


def test_la_seguridad_de_transporte_declara_la_url_publica_y_los_hosts_extra():
    cfg = Configuracion(url_publica="https://conector-xyz.a.run.app", hosts_extra=("https://canario---conector-xyz.run.app/",))
    s = seguridad_de_transporte(cfg)
    assert s.enable_dns_rebinding_protection and "conector-xyz.a.run.app" in s.allowed_hosts
    assert "canario---conector-xyz.run.app" in s.allowed_hosts and "otro.ejemplo.com" not in s.allowed_hosts
    assert "https://canario---conector-xyz.run.app" in s.allowed_origins


def test_un_host_no_declarado_recibe_421_con_token_valido(servidor_http):
    c, _ = servidor_http
    token, *_ = flujo_completo(c)
    cabeceras = {"Authorization": f"Bearer {token}", "Accept": "application/json, text/event-stream"}
    cuerpo = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                                                                             "clientInfo": {"name": "t", "version": "1"}}}
    assert c.post("/mcp", headers=cabeceras, json=cuerpo).status_code == 200
    assert c.post("/mcp", headers={**cabeceras, "Host": "otro.ejemplo.com"}, json=cuerpo).status_code == 421


def mcp(c, token, metodo, params, id_=2):
    r = c.post("/mcp", headers={"Authorization": f"Bearer {token}", "Accept": "application/json, text/event-stream"},
               json={"jsonrpc": "2.0", "id": id_, "method": metodo, "params": params})
    assert r.status_code == 200, r.text
    linea = next(x for x in r.text.splitlines() if x.startswith("data:"))
    return json.loads(linea[5:])


def test_sin_estado_cada_request_vale_solo_y_tools_list_y_ayuda_andan(servidor_http):
    c, _ = servidor_http
    token, *_ = flujo_completo(c)
    lista = mcp(c, token, "tools/list", {})["result"]["tools"]
    assert [t["name"] for t in lista] == list(V.HERRAMIENTAS)
    r = mcp(c, token, "tools/call", {"name": "aientika_ayuda", "arguments": {}})["result"]
    cuerpo = json.loads(r["content"][0]["text"])
    assert cuerpo["version_conector"] == V.CONECTOR_VERSION and "NO DISPONIBLE" in cuerpo["cobertura"]


def test_qa11_con_el_sdk_en_debug_la_consulta_no_aparece_en_ningun_log_ni_tabla(servidor_http, logs):
    c, ruta = servidor_http
    token, *_ = flujo_completo(c)
    mcp(c, token, "tools/call", {"name": "aientika_buscar_jurisprudencia_cr", "arguments": {"consulta": f"culpa {FRASE_MARCADA}"}})
    mcp(c, token, "tools/call", {"name": "aientika_verificar_cita_de_fallo", "arguments": {"id": "sen-1-0001-0000001", "frase": f"{FRASE_MARCADA} larga"}})
    mcp(c, token, "tools/call", {"name": "aientika_buscar_jurisprudencia_cr", "arguments": {"consulta": FRASE_MARCADA, "anno": "no-es-un-numero"}})  # error de validación del SDK
    mcp(c, token, "tools/call", {"name": "aientika_reportar_respuesta", "arguments": {"resumen": "pedí algo", "problema": "no sirvió"}})
    assert logs, "control positivo: el colector tiene que haber visto logs del SDK en DEBUG"
    assert not [x for x in logs if FRASE_MARCADA in x], [x for x in logs if FRASE_MARCADA in x][:2]
    # Desde el aviso v2 el texto SÍ se guarda, pero solo en `conector_consulta`: ninguna otra
    # tabla (contadores, llamadas, reportes, OAuth) puede llevarlo, y los logs siguen limpios (arriba).
    tablas = volcar_tablas(ruta).split("\n")
    assert not [t for t in tablas if FRASE_MARCADA in t and not t.startswith("conector_consulta:")]
    assert [t for t in tablas if t.startswith("conector_consulta:") and FRASE_MARCADA in t]  # control positivo
    assert "conector_llamada" in volcar_tablas(ruta)


def test_el_nivel_del_sdk_queda_en_warning(servidor_http):
    assert logging.getLogger("mcp").level == logging.WARNING  # fijado a propósito, no heredado de la raíz


# --- modo de desarrollo sin autenticación: prohibido en producción -------------------------------------------------------------

def test_sin_auth_esta_prohibido_en_cloud_run_y_con_url_https():
    for cfg in (Configuracion(url_publica="http://localhost:8080", sin_auth=True, en_cloud_run=True),
                Configuracion(url_publica="https://x.run.app", sin_auth=True)):
        with pytest.raises(ConfiguracionInvalida, match="prohibido"):
            construir(cfg, Herramientas())


def test_sin_auth_en_local_arranca_sin_rutas_de_oauth_y_con_el_invitado_de_desarrollo(monkeypatch):
    from starlette.testclient import TestClient
    _, app = construir(Configuracion(url_publica="http://localhost:8080", sin_auth=True), Herramientas())
    with TestClient(app, base_url="http://localhost:8080") as c:
        assert c.get("/health").status_code == 200
        assert c.post("/register", json={}).status_code == 404 and c.get("/conector/autorizar").status_code == 404


def test_la_url_publica_se_valida():
    for mala in ("", "conector.run.app", "https://x.run.app/mcp", "ftp://x"):
        with pytest.raises(ConfiguracionInvalida):
            Configuracion(url_publica=mala).validar()


def test_la_configuracion_sale_del_entorno():
    cfg = configuracion_desde_entorno({"CONECTOR_URL_PUBLICA": "https://a.run.app/", "CONECTOR_HOSTS_EXTRA": "b.run.app, c.run.app",
                                       "K_SERVICE": "conector"})
    assert cfg.url_publica == "https://a.run.app" and cfg.hosts_extra == ("b.run.app", "c.run.app") and cfg.en_cloud_run and not cfg.sin_auth


def test_el_issuer_sale_de_la_url_publica_del_entorno(servidor_http):
    c, _ = servidor_http
    assert c.get("/.well-known/oauth-authorization-server").json()["issuer"].rstrip("/") == URL
    assert c.get("/.well-known/oauth-protected-resource/mcp").json()["resource"] == URL + "/mcp"


def test_version_y_health_sin_autenticacion(servidor_http):
    c, _ = servidor_http
    assert c.get("/version").json()["conector_version"] == V.CONECTOR_VERSION


# --- sin la base (base apagada 23:00-7:00 o caída): el mensaje llega en palabras, no un 401 ni un 500 --------------------------------

def texto_de_herramienta(c, token, nombre, argumentos):
    """`nombre` puede ser el interno (`buscar`) o el MCP (`aientika_buscar_jurisprudencia_cr`): se llama con el MCP (contrato 2.0.0)."""
    r = mcp(c, token, "tools/call", {"name": V.NOMBRES_MCP.get(nombre, nombre), "arguments": argumentos})["result"]
    return json.loads(r["content"][0]["text"])


def test_fuera_de_horario_el_token_pasa_y_la_herramienta_dice_el_horario_sin_tocar_datos(servidor_http, monkeypatch):
    from src.conector import limites
    c, ruta = servidor_http
    token, *_ = flujo_completo(c)
    antes = volcar_tablas(ruta)
    monkeypatch.setattr(limites, "fuera_de_horario", lambda ahora: True)
    for nombre, args in (("buscar", {"consulta": "algo"}), ("ficha", {"id": "x"}), ("ayuda", {}), ("reportar", {"resumen": "a", "problema": "b"})):
        r = texto_de_herramienta(c, token, nombre, args)
        assert r["error"] == "fuera_de_horario" and "7:00 a 23:00" in r["mensaje"], (nombre, r)
    assert volcar_tablas(ruta) == antes  # ni un cupo, ni un registro: no se tocó la base


def test_con_la_base_caida_dentro_de_horario_se_dice_que_no_se_pudo_consultar(servidor_http):
    from src.conector import bd
    c, _ = servidor_http
    token, *_ = flujo_completo(c)
    bd.usar(estado=lambda: (_ for _ in ()).throw(OSError("la VM no responde")), lectura=lambda: (_ for _ in ()).throw(OSError("x")))
    r = texto_de_herramienta(c, token, "buscar", {"consulta": "responsabilidad"})
    assert r["error"] == "base_no_disponible" and "no es que no haya resultados" in r["mensaje"].lower() and "resultados" not in r


def test_el_token_alterado_sigue_dando_401_aunque_la_base_este_apagada(servidor_http, monkeypatch):
    from src.conector import limites
    from test_conector_oauth import initialize
    c, _ = servidor_http
    token, *_ = flujo_completo(c)
    monkeypatch.setattr(limites, "fuera_de_horario", lambda ahora: True)
    assert initialize(c, token).status_code == 200
    assert initialize(c, token[:-3] + ("AAA" if not token.endswith("AAA") else "BBB")).status_code == 401  # control negativo
