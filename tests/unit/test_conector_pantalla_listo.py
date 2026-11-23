"""Pantalla «Listo» después de autorizar: Claude y ChatGPT web ven cómo hacer la primera consulta y
la señal de que funcionó, y vuelven solos al asistente; Claude Desktop (retorno local) sigue con el 303 inmediato.

Control: el código de autorización que lleva el botón se canjea (la pantalla no rompe el OAuth) y la pantalla no lleva scripts.
"""

from urllib.parse import parse_qs, urlsplit

from conector_apoyo import CALLBACK, URL, invitar, pkce, registrar_cliente, retorno, servidor_http  # noqa: F401

from src.conector import pantalla_listo

CHATGPT = "https://chatgpt.com/connector/oauth/abc123"
LOCAL = "http://localhost:33418/oauth/callback"


def _autorizar(c, redirect):
    _, codigo = invitar()
    verifier, challenge = pkce()
    cid = registrar_cliente(c, uris=[redirect]).json()["client_id"]
    r = c.get("/authorize", params={"response_type": "code", "client_id": cid, "redirect_uri": redirect, "code_challenge": challenge,
                                    "code_challenge_method": "S256", "state": "e", "resource": URL + "/mcp", "scope": "consulta"})
    assert r.status_code == 302, r.text
    p = c.get(r.headers["location"])
    s = parse_qs(urlsplit(r.headers["location"]).query)["s"][0]
    nonce = p.text.split("name='nonce' value='")[1].split("'")[0]
    final = c.post("/conector/autorizar", data={"s": s, "nonce": nonce, "codigo": codigo, "accion": "autorizar"})
    return cid, final, verifier, redirect


def _canjea(c, cid, url, redirect, verifier):
    code = parse_qs(urlsplit(url).query)["code"][0]
    t = c.post("/token", data={"grant_type": "authorization_code", "code": code, "redirect_uri": redirect, "client_id": cid,
                               "code_verifier": verifier, "resource": URL + "/mcp"})
    return t.status_code == 200 and "access_token" in t.json()


def test_claude_ve_listo_con_la_primera_consulta_y_vuelve_solo_con_un_codigo_que_canjea(servidor_http):
    c, _ = servidor_http
    cid, final, verifier, redirect = _autorizar(c, CALLBACK)
    assert final.status_code == 200 and "Listo: Aiéntika quedó conectado" in final.text
    assert "aientika, " + pantalla_listo.EJEMPLO in final.text.replace("&#x27;", "'") and pantalla_listo.SENAL in final.text
    assert f"http-equiv='refresh' content='{pantalla_listo.ESPERA_S};url=" in final.text and "Volver a Claude" in final.text
    assert "<script" not in final.text.lower()  # la CSP no permite scripts: la vuelta es por meta refresh y botón
    url = retorno(final)
    assert url.startswith(CALLBACK + "?code=") and "&state=e" in url
    assert _canjea(c, cid, url, redirect, verifier)


def test_chatgpt_ve_listo_con_el_menu_arroba(servidor_http):
    c, _ = servidor_http
    cid, final, verifier, redirect = _autorizar(c, CHATGPT)
    assert final.status_code == 200 and "@ai</b>" in final.text and "@aien" not in final.text and "Volver a ChatGPT" in final.text
    # En ChatGPT la línea de fuente no es una señal confiable (2026-11-15): la pantalla no la promete
    assert pantalla_listo.SENAL not in final.text and "enlace oficial" in final.text
    assert _canjea(c, cid, retorno(final), redirect, verifier)


def test_desktop_sigue_volviendo_enseguida(servidor_http):
    c, _ = servidor_http
    cid, final, verifier, redirect = _autorizar(c, LOCAL)
    assert final.status_code == 303 and "Listo" not in final.text  # control: el retorno local no pasa por la pantalla
    assert _canjea(c, cid, final.headers["location"], redirect, verifier)


def test_la_espera_es_mucho_menor_que_la_vigencia_del_codigo():
    from src.conector.oauth import VIGENCIA_CODIGO_S
    assert pantalla_listo.ESPERA_S * 10 <= VIGENCIA_CODIGO_S
