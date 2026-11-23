"""«Recordarme en este equipo» en la pantalla de alta, para el
conector en ChatGPT y en Claude.

Se mide el resultado: con la casilla, la próxima conexión desde el mismo navegador pasa sin código y el código emitido sirve en
`/token`. Controles: sin la casilla no hay recuerdo; la cookie no lleva el código; una cookie alterada o de un invitado dado de baja
no vale; «Usar otro código» la borra. Igual para el retorno de ChatGPT.
"""

from urllib.parse import parse_qs, urlsplit

from conector_apoyo import retorno as url_retorno
from conector_apoyo import CALLBACK, URL, invitar, pkce, registrar_cliente, servidor_http  # noqa: F401

from src.conector import bd, invitados
from src.conector.pantalla import COOKIE_RECORDAR

CHATGPT = "https://chatgpt.com/connector_platform_oauth_redirect"


def _pantalla(c, retorno=CALLBACK):
    """Registra un cliente, pasa por /authorize; devuelve (client_id, s, nonce, html de la pantalla, verifier)."""
    cid = registrar_cliente(c, uris=[retorno]).json()["client_id"]
    verifier, challenge = pkce()
    r = c.get("/authorize", params={"response_type": "code", "client_id": cid, "redirect_uri": retorno, "code_challenge": challenge,
                                    "code_challenge_method": "S256", "state": "e", "resource": URL + "/mcp", "scope": "consulta"})
    assert r.status_code == 302, r.text
    p = c.get(r.headers["location"])
    assert p.status_code == 200
    s = parse_qs(urlsplit(r.headers["location"]).query)["s"][0]
    nonce = p.text.split("name='nonce' value='")[1].split("'")[0]
    return cid, s, nonce, p.text, verifier


def _canjea(c, cid, respuesta, retorno, verifier):
    code = parse_qs(urlsplit(url_retorno(respuesta)).query)["code"][0]
    t = c.post("/token", data={"grant_type": "authorization_code", "code": code, "redirect_uri": retorno, "client_id": cid,
                               "code_verifier": verifier, "resource": URL + "/mcp"})
    return t.status_code == 200 and "access_token" in t.json()


def test_con_la_casilla_la_segunda_conexion_pasa_sin_codigo_en_claude_y_en_chatgpt(servidor_http):
    c, _ = servidor_http
    _, codigo = invitar("equipo")
    cid, s, nonce, html, _v = _pantalla(c)
    assert "Recordarme en este equipo" in html
    r = c.post("/conector/autorizar", data={"s": s, "nonce": nonce, "codigo": codigo, "accion": "autorizar", "recordar": "1"})
    assert "code=" in url_retorno(r)
    galleta = c.cookies.get(COOKIE_RECORDAR)
    assert galleta and invitados.normalizar(codigo) not in galleta.upper()  # la cookie no lleva el código
    for retorno in (CALLBACK, CHATGPT):  # nueva conexión, otro cliente, mismo navegador
        cid2, s2, nonce2, html2, verifier2 = _pantalla(c, retorno)
        assert "te recuerda como <b>equipo</b>" in html2 and "name='codigo'" not in html2
        r2 = c.post("/conector/autorizar", data={"s": s2, "nonce": nonce2, "accion": "autorizar"})
        assert url_retorno(r2), r2.text
        assert _canjea(c, cid2, r2, retorno, verifier2)


def test_sin_la_casilla_no_hay_recuerdo(servidor_http):
    c, _ = servidor_http
    _, codigo = invitar()
    cid, s, nonce, _h, _v = _pantalla(c)
    assert c.post("/conector/autorizar", data={"s": s, "nonce": nonce, "codigo": codigo, "accion": "autorizar"}).status_code == 200
    assert not c.cookies.get(COOKIE_RECORDAR)
    _, s2, nonce2, html2, _v2 = _pantalla(c)
    assert "name='codigo'" in html2
    assert c.post("/conector/autorizar", data={"s": s2, "nonce": nonce2, "accion": "autorizar"}).status_code == 401


def test_cookie_alterada_no_vale(servidor_http):
    c, _ = servidor_http
    c.cookies.set(COOKIE_RECORDAR, "eyJhbGciOiJIUzI1NiJ9.eyJpbnYiOiJpbnYtMSJ9.firmafalsa", domain="conector.test", path="/conector/autorizar")
    _, s, nonce, html, _v = _pantalla(c)
    assert "name='codigo'" in html
    assert c.post("/conector/autorizar", data={"s": s, "nonce": nonce, "accion": "autorizar"}).status_code == 401


def test_la_baja_del_invitado_anula_el_recuerdo(servidor_http):
    c, _ = servidor_http
    id_, codigo = invitar()
    _, s, nonce, _h, _v = _pantalla(c)
    c.post("/conector/autorizar", data={"s": s, "nonce": nonce, "codigo": codigo, "accion": "autorizar", "recordar": "1"})
    assert c.cookies.get(COOKIE_RECORDAR)
    with bd.estado() as conn:
        invitados.baja(conn.cursor(), id_, 2000)
    _, s2, nonce2, html2, _v2 = _pantalla(c)
    assert "name='codigo'" in html2
    assert c.post("/conector/autorizar", data={"s": s2, "nonce": nonce2, "accion": "autorizar"}).status_code == 401


def test_recargar_o_reenviar_despues_de_autorizar_dice_que_ya_quedo_conectado(servidor_http):
    # autorizó bien (303 y /token 200) y después vio «Esta solicitud venció o no es válida» al recargar.
    from src.conector.pantalla import MENSAJE_YA_AUTORIZADO
    c, _ = servidor_http
    _, codigo = invitar()
    _, s, nonce, _h, _v = _pantalla(c)
    datos = {"s": s, "nonce": nonce, "codigo": codigo, "accion": "autorizar"}
    assert url_retorno(c.post("/conector/autorizar", data=datos))
    reenvio = c.post("/conector/autorizar", data=datos)  # el nonce ya se consumió
    recarga = c.get("/conector/autorizar")  # sin ?s=
    for r in (reenvio, recarga):
        assert r.status_code == 400 and "ya quedó conectado" in r.text
    assert "ya quedó conectado" in MENSAJE_YA_AUTORIZADO
    vencida = c.get("/conector/autorizar", params={"s": "no-es-una-solicitud"})  # control: una solicitud mala sigue siendo error
    assert vencida.status_code == 400 and "venció o no es válida" in vencida.text


def test_usar_otro_codigo_borra_el_recuerdo(servidor_http):
    c, _ = servidor_http
    _, codigo = invitar()
    _, s, nonce, _h, _v = _pantalla(c)
    c.post("/conector/autorizar", data={"s": s, "nonce": nonce, "codigo": codigo, "accion": "autorizar", "recordar": "1"})
    _, s2, nonce2, _h2, _v2 = _pantalla(c)
    r = c.post("/conector/autorizar", data={"s": s2, "nonce": nonce2, "accion": "olvidar"})
    assert r.status_code == 200 and "name='codigo'" in r.text
    assert not c.cookies.get(COOKIE_RECORDAR)
