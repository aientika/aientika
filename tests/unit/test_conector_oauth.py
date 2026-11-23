"""OAuth del conector de punta a punta por HTTP: lista blanca de retornos, PKCE, canje atómico, reuso, refresh, `resource`, revocación.

Cada detector tiene su control: el caso malo se rechaza Y el bueno pasa. Los casos de la lista blanca
(`claude.ai.evil.com`, `claude.ai@evil.com`, query, fragmento). Se mide el resultado —qué token entra o no a `/mcp`— y no el componente.
"""

import threading
from urllib.parse import parse_qs, urlsplit

import pytest
from conector_apoyo import CALLBACK, URL, invitar, pkce, registrar_cliente, retorno, volcar_tablas

from src.conector import bd, lista_blanca as LB, oauth

MALOS = ["https://claude.ai.evil.com/api/mcp/auth_callback", "https://claude.ai@evil.com/api/mcp/auth_callback",
         "https://claude.ai/api/mcp/auth_callback?x=1", "https://claude.ai/api/mcp/auth_callback#f", "https://evil.com/cb",
         "http://claude.ai/api/mcp/auth_callback", "https://claude.ai:8443/api/mcp/auth_callback", "https://claude.ai/otra/ruta",
         "http://evil.com:3000/callback"]
BUENOS = [CALLBACK, "https://claude.com/api/mcp/auth_callback", "http://localhost:51234/callback", "http://127.0.0.1:9/cb"]


def autorizar(c, codigo_invitado, challenge, state="estado-1", resource=URL + "/mcp"):
    """Registra un cliente, pasa por /authorize y la pantalla; devuelve (client_id, redirect final)."""
    cid = registrar_cliente(c).json()["client_id"]
    r = c.get("/authorize", params={"response_type": "code", "client_id": cid, "redirect_uri": CALLBACK, "code_challenge": challenge,
                                    "code_challenge_method": "S256", "state": state, "resource": resource, "scope": "consulta"})
    assert r.status_code == 302 and r.headers["location"].startswith("/conector/autorizar?s="), r.text
    pantalla = c.get(r.headers["location"])
    assert pantalla.status_code == 200
    s = parse_qs(urlsplit(r.headers["location"]).query)["s"][0]
    nonce = pantalla.text.split("name='nonce' value='")[1].split("'")[0]
    return cid, c.post("/conector/autorizar", data={"s": s, "nonce": nonce, "codigo": codigo_invitado, "accion": "autorizar"})


def canjear(c, cid, code, verifier, **extra):
    return c.post("/token", data={"grant_type": "authorization_code", "code": code, "redirect_uri": CALLBACK, "client_id": cid,
                                  "code_verifier": verifier, "resource": URL + "/mcp", **extra})


def flujo_completo(c):
    """Invitado nuevo, flujo entero; devuelve (token, client_id, code, verifier)."""
    _, codigo = invitar()
    verifier, challenge = pkce()
    cid, final = autorizar(c, codigo, challenge)
    assert retorno(final), final.text
    code = parse_qs(urlsplit(retorno(final)).query)["code"][0]
    r = canjear(c, cid, code, verifier)
    assert r.status_code == 200, r.text
    return r.json()["access_token"], cid, code, verifier


def initialize(c, token, ruta="/mcp"):
    return c.post(ruta, headers={"Authorization": f"Bearer {token}", "Accept": "application/json, text/event-stream"},
                  json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
                        "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}})


@pytest.mark.parametrize("uri", MALOS)
def test_lista_blanca_rechaza_retornos_ajenos(servidor_http, uri):
    c, _ = servidor_http
    r = registrar_cliente(c, uris=[uri])
    assert r.status_code == 400 and r.json()["error"] == "invalid_redirect_uri"
    assert "oauth_cliente: []" in volcar_tablas(servidor_http[1])  # no quedó registrado


@pytest.mark.parametrize("uri", BUENOS)
def test_lista_blanca_acepta_los_retornos_de_claude(servidor_http, uri):
    assert registrar_cliente(servidor_http[0], uris=[uri]).status_code == 201


CHATGPT_BUENOS = ["https://chatgpt.com/connector_platform_oauth_redirect", "https://chatgpt.com/connector/oauth/abc_123-XYZ"]
CHATGPT_MALOS = ["https://chatgpt.com.evil.com/connector_platform_oauth_redirect", "https://chatgpt.com@evil.com/connector/oauth/a",
                 "https://chatgpt.com/connector/oauth/a/b", "https://chatgpt.com/connector/oauth/", "https://chatgpt.com/connector/oauth/a?x=1",
                 "http://chatgpt.com/connector_platform_oauth_redirect", "https://chatgpt.com:8443/connector/oauth/a",
                 "https://chatgpt.com/otra/ruta", "https://openai.com/connector/oauth/a"]


@pytest.mark.parametrize("uri", CHATGPT_BUENOS)
def test_lista_blanca_acepta_los_retornos_de_chatgpt(servidor_http, uri):
    # Retornos de developers.openai.com/apps-sdk/build/auth.
    assert registrar_cliente(servidor_http[0], uris=[uri]).status_code == 201
    assert LB.etiqueta_de([uri]) == LB.ETIQUETA_CHATGPT and LB.tipo_retorno(uri) == "chatgpt"


@pytest.mark.parametrize("uri", CHATGPT_MALOS)
def test_lista_blanca_rechaza_imitaciones_de_chatgpt(servidor_http, uri):
    r = registrar_cliente(servidor_http[0], uris=[uri])
    assert r.status_code == 400 and r.json()["error"] == "invalid_redirect_uri"


def test_una_uri_buena_al_lado_de_una_mala_no_alcanza(servidor_http):
    assert registrar_cliente(servidor_http[0], uris=[CALLBACK, MALOS[0]]).status_code == 400


def test_la_lista_blanca_se_comporta_como_se_documenta():
    assert LB.redirect_uris_validas([CALLBACK]) and not LB.redirect_uris_validas([])
    assert LB.etiqueta_de([CALLBACK]) == LB.ETIQUETA_WEB
    assert "saldo" not in LB.__doc__


def test_techo_de_registros_por_ip(servidor_http):
    c, _ = servidor_http
    cab = {"X-Forwarded-For": "9.9.9.9"}
    for _ in range(oauth.MAX_REGISTROS_POR_IP_HORA):
        assert c.post("/register", headers=cab, json={"redirect_uris": [CALLBACK], "grant_types": ["authorization_code", "refresh_token"],
                                                     "response_types": ["code"], "token_endpoint_auth_method": "none"}).status_code == 201
    assert registrar_cliente(c).status_code == 201  # otra IP (la del socket): control, no se bloquea
    r = c.post("/register", headers=cab, json={"redirect_uris": [CALLBACK], "grant_types": ["authorization_code", "refresh_token"],
                                              "response_types": ["code"], "token_endpoint_auth_method": "none"})
    assert r.status_code == 400 and "Demasiados" in r.json()["error_description"]


def test_la_ip_del_registro_no_se_guarda_en_claro(servidor_http):
    c, ruta = servidor_http
    c.post("/register", headers={"X-Forwarded-For": "203.0.113.77"}, json={"redirect_uris": [CALLBACK], "grant_types": ["authorization_code"],
                                                                         "response_types": ["code"], "token_endpoint_auth_method": "none"})
    assert "203.0.113.77" not in volcar_tablas(ruta) and oauth.hash_ip("203.0.113.77") in volcar_tablas(ruta)


def test_flujo_completo_entrega_un_token_que_entra_a_mcp_con_y_sin_barra(servidor_http):
    c, _ = servidor_http
    token, *_ = flujo_completo(c)
    for ruta in ("/mcp", "/mcp/"):  # : la barra no da 307
        r = initialize(c, token, ruta)
        assert r.status_code == 200, (ruta, r.status_code, r.text)
        assert "Aiéntika" in r.text  # nombre del producto
    assert c.post("/mcp", json={}).status_code == 401  # control negativo: sin token no entra


def test_sin_resource_o_con_otro_resource_se_rechaza(servidor_http):
    c, _ = servidor_http
    _, challenge = pkce()
    cid = registrar_cliente(c).json()["client_id"]
    for resource in (None, "https://otro.test/mcp"):
        params = {"response_type": "code", "client_id": cid, "redirect_uri": CALLBACK, "code_challenge": challenge,
                  "code_challenge_method": "S256", "state": "st", **({"resource": resource} if resource else {})}
        r = c.get("/authorize", params=params)
        assert r.status_code == 302 and "error=invalid_request" in r.headers["location"]
        assert r.headers["location"].startswith(CALLBACK)


def test_codigo_de_invitado_malo_no_autoriza_y_el_bueno_si(servidor_http):
    c, ruta = servidor_http
    _, codigo = invitar()
    _, challenge = pkce()
    _, malo = autorizar(c, "AAAA-AAAA-AAAA-AAAA", challenge)
    assert malo.status_code == 401 and "inválido" in malo.text and "oauth_codigo: []" in volcar_tablas(ruta)
    _, bueno = autorizar(c, codigo, challenge)
    assert bueno.status_code == 200 and retorno(bueno).startswith(CALLBACK + "?code=")  # pantalla «Listo», con el botón de vuelta


def test_invitado_dado_de_baja_no_autoriza(servidor_http):
    from src.conector import invitados
    c, _ = servidor_http
    id_, codigo = invitar()
    with bd.estado() as conn:
        invitados.baja(conn.cursor(), id_, 2000)
    assert autorizar(c, codigo, pkce()[1])[1].status_code == 401


def test_pkce_con_otro_verifier_no_canjea(servidor_http):
    c, _ = servidor_http
    _, codigo = invitar()
    verifier, challenge = pkce()
    cid, final = autorizar(c, codigo, challenge)
    code = parse_qs(urlsplit(retorno(final)).query)["code"][0]
    assert canjear(c, cid, code, pkce()[0]).status_code == 400
    assert canjear(c, cid, code, verifier).status_code == 200  # el código no se quemó por un verifier malo


def test_cancelar_vuelve_a_claude_con_access_denied(servidor_http):
    c, _ = servidor_http
    cid = registrar_cliente(c).json()["client_id"]
    r = c.get("/authorize", params={"response_type": "code", "client_id": cid, "redirect_uri": CALLBACK, "code_challenge": pkce()[1],
                                    "code_challenge_method": "S256", "state": "st", "resource": URL + "/mcp"})
    s = parse_qs(urlsplit(r.headers["location"]).query)["s"][0]
    nonce = c.get(r.headers["location"]).text.split("name='nonce' value='")[1].split("'")[0]
    f = c.post("/conector/autorizar", data={"s": s, "nonce": nonce, "accion": "cancelar"})
    assert f.status_code == 303 and "error=access_denied" in f.headers["location"] and f.headers["location"].startswith(CALLBACK)


def test_post_sin_el_nonce_de_la_cookie_se_rechaza(servidor_http):
    c, _ = servidor_http
    _, codigo = invitar()
    cid = registrar_cliente(c).json()["client_id"]
    r = c.get("/authorize", params={"response_type": "code", "client_id": cid, "redirect_uri": CALLBACK, "code_challenge": pkce()[1],
                                    "code_challenge_method": "S256", "state": "st", "resource": URL + "/mcp"})
    s = parse_qs(urlsplit(r.headers["location"]).query)["s"][0]
    c.get(r.headers["location"])
    assert c.post("/conector/autorizar", data={"s": s, "nonce": "inventado", "codigo": codigo}).status_code == 400
    assert c.post("/conector/autorizar", data={"s": "no-firmada", "nonce": "x", "codigo": codigo}).status_code == 400


def test_intentos_por_ip_se_cuentan_antes_de_mirar_el_codigo(servidor_http):
    from src.conector import pantalla
    c, _ = servidor_http
    _, challenge = pkce()
    for _ in range(pantalla.INTENTOS_POR_IP):
        assert autorizar(c, "BBBB-BBBB-BBBB-BBBB", challenge)[1].status_code == 401
    _, codigo = invitar()
    assert autorizar(c, codigo, challenge)[1].status_code == 429  # ni el código bueno pasa tras agotar los intentos


def test_el_codigo_de_autorizacion_se_guarda_solo_como_hash(servidor_http):
    c, ruta = servidor_http
    _, codigo = invitar()
    cid, final = autorizar(c, codigo, pkce()[1])
    code = parse_qs(urlsplit(retorno(final)).query)["code"][0]
    volcado = volcar_tablas(ruta)
    assert code not in volcado and oauth.hash_codigo_autorizacion(code) in volcado and codigo not in volcado


def test_reuso_del_codigo_falla_y_revoca_lo_emitido(servidor_http):
    c, _ = servidor_http
    token, cid, code, verifier = flujo_completo(c)
    assert initialize(c, token).status_code == 200
    r = canjear(c, cid, code, verifier)
    assert r.status_code == 400 and r.json()["error"] == "invalid_grant"
    assert initialize(c, token).status_code == 401  # lo emitido murió con el reuso


def test_canje_concurrente_solo_gana_uno(servidor_http):
    c, _ = servidor_http
    _, codigo = invitar()
    verifier, challenge = pkce()
    cid, final = autorizar(c, codigo, challenge)
    code = parse_qs(urlsplit(retorno(final)).query)["code"][0]
    resultados, barrera = [], threading.Barrier(2)

    def pedir():
        barrera.wait()
        resultados.append(canjear(c, cid, code, verifier).status_code)

    hilos = [threading.Thread(target=pedir) for _ in range(2)]
    [h.start() for h in hilos]
    [h.join() for h in hilos]
    assert resultados.count(200) <= 1  # nunca dos credenciales de un mismo código (si el perdedor revoca, el ganador también cae)
    with bd.estado() as conn:
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM credencial")
        assert cur.fetchone()[0] == 1


def test_el_refresh_no_se_emite_ni_se_acepta_ni_se_anuncia(servidor_http):
    c, _ = servidor_http
    meta = c.get("/.well-known/oauth-authorization-server").json()
    assert "refresh_token" not in meta["grant_types_supported"] and "authorization_code" in meta["grant_types_supported"]
    token, cid, *_ = flujo_completo(c)
    otro = c.post("/token", data={"grant_type": "refresh_token", "refresh_token": "cualquiera", "client_id": cid})
    assert otro.status_code == 400
    tok = c.post("/token", data={"grant_type": "authorization_code", "code": "x", "client_id": cid})
    assert "refresh_token" not in tok.text


def test_el_registro_sin_refresh_pasa_igual_porque_el_sdk_lo_exige(servidor_http):
    r = registrar_cliente(servidor_http[0], grants=("authorization_code",))
    assert r.status_code == 201  # sin la corrección al vuelo del registro, el SDK lo rechazaría


def test_revoke_mata_el_token(servidor_http):
    c, _ = servidor_http
    token, cid, *_ = flujo_completo(c)
    assert initialize(c, token).status_code == 200
    # el SDK exige el campo `client_secret` aunque venga vacío en un cliente público (quirk de RevocationRequest)
    r = c.post("/revoke", data={"token": token, "client_id": cid, "client_secret": ""})
    assert r.status_code == 200, r.text
    assert initialize(c, token).status_code == 401


def test_dar_de_baja_al_invitado_cierra_su_sesion_en_el_acto(servidor_http):
    from src.conector import invitados
    c, _ = servidor_http
    token, *_ = flujo_completo(c)
    with bd.estado() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM invitado")
        invitados.baja(cur, cur.fetchone()[0], 3000)
    assert initialize(c, token).status_code == 401


def test_token_vencido_o_alterado_da_401(servidor_http):
    from datetime import datetime, timedelta, timezone
    from src.conector.token import emitir_jwt
    c, _ = servidor_http
    token, *_ = flujo_completo(c)
    assert initialize(c, token[:-3] + ("AAA" if not token.endswith("AAA") else "BBB")).status_code == 401
    viejo, _ = emitir_jwt("inv-x", "jti-x", datetime.now(timezone.utc) - timedelta(days=100))
    assert initialize(c, viejo).status_code == 401


def test_el_token_dura_90_dias(servidor_http):
    from src.conector.token import DIAS_VIGENCIA, decodificar
    c, _ = servidor_http
    token, *_ = flujo_completo(c)
    d = decodificar(token)
    assert abs((d["exp"] - d["iat"]) - DIAS_VIGENCIA * 86400) < 5 and d["jti"] and d["sub"].startswith("inv-")


def test_la_pantalla_es_form_post_nativo_con_aviso_de_privacidad_y_sin_el_nombre_declarado(servidor_http):
    from src.conector.pantalla import AVISO_PRIVACIDAD
    c, _ = servidor_http
    cid = c.post("/register", json={"redirect_uris": [CALLBACK], "client_name": "Claude - confirma tu codigo en evil.com",
                                    "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"],
                                    "token_endpoint_auth_method": "none"}).json()["client_id"]
    r = c.get("/authorize", params={"response_type": "code", "client_id": cid, "redirect_uri": CALLBACK, "code_challenge": pkce()[1],
                                    "code_challenge_method": "S256", "state": "st", "resource": URL + "/mcp"})
    html = c.get(r.headers["location"]).text
    assert "<form method='POST'" in html and "evil.com" not in html and LB.ETIQUETA_WEB in html
    # Aviso v2: ya no promete que el texto no se guarda; dice que se guarda 90 días.
    assert "También se guarda, durante 90 días, el texto de tus búsquedas" in html and "Qué se guarda: la huella" in html
    assert "Qué NO se guarda" not in html and AVISO_PRIVACIDAD.count("Qué") == 1
