"""Pantalla `/conector/autorizar`: el invitado pone su código y el servidor le entrega a Claude un código de autorización.

Es el paso del medio del OAuth: `/authorize` (SDK) valida al cliente y manda acá con la solicitud firmada; acá se valida a la PERSONA.
Formulario `<form method="POST">` nativo. Reglas, en este orden: (1) la solicitud firmada vence a los 10 min y el POST debe traer
el nonce de la cookie que se sirvió con la pantalla; (2) «Cancelar» vuelve a Claude con `access_denied`, solo al `redirect_uri` ya
validado; (3) el límite de intentos se cuenta ANTES de mirar el código (por IP y global); (4) el código debe ser de un invitado activo.
Se muestra la etiqueta canónica del cliente, nunca el `client_name` que declaró (anti-phishing). Fuera del horario de atención
(si está restringido) o con la base sin responder se dice en palabras: la pantalla no inventa un «código inválido» por una falla nuestra.
"""

from __future__ import annotations

import html
import logging
import secrets
from datetime import datetime, timedelta, timezone

from mcp.server.auth.provider import construct_redirect_uri
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse

from src.conector import bd, invitados, limites, pantalla_listo, solicitud
from src.conector.lista_blanca import tipo_retorno
from src.conector.version import CONSTRUIDO_POR, NOMBRE_PRODUCTO, SITIO_AUTOR
from src.conector.oauth import RUTA_PANTALLA, emitir_codigo, hash_ip

logger = logging.getLogger(__name__)

INTENTOS_POR_IP = 10
INTENTOS_GLOBALES_HORA = 1000  # no defiende de la adivinanza (el código tiene ~79 bits): solo frena un desborde
COOKIE_NONCE = "conector_nonce"
# El aviso se versiona y no se edita en silencio: la versión que la persona tuvo delante viaja con el código de autorización
# hasta su credencial, y de ella depende qué se guarda. v1 prometía «Qué NO se guarda: el texto de tus consultas»; las credenciales
# emitidas con v1 conservan esa promesa (registro.AVISO_MINIMO_TEXTO). v2 guarda el texto de las consultas por 90 días. v3 agrega que
# la visita al sitio desde el enlace de una respuesta se une a la búsqueda; solo las credenciales v3 o posteriores llevan la
# referencia en el enlace (referencia_visita.AVISO_MINIMO_VISITA).
AVISO_VERSION = 4  # v4: el enlace de las respuestas va a aientika.ai
# «Recordarme en este equipo». La cookie lleva SOLO el id del invitado, firmado (JWT HS256 con
# CONECTOR_FIRMA_SECRET), nunca el código. HttpOnly, SameSite=Lax y limitada a la ruta de la pantalla. Vale 90 días y cae sola si el
# invitado se da de baja. No autoriza sola: la persona igual tiene que tocar «Autorizar», con la etiqueta del cliente a la vista.
MENSAJE_YA_AUTORIZADO = (f"Si ya autorizaste, volvé a tu asistente: {NOMBRE_PRODUCTO} ya quedó conectado y podés cerrar esta "
                         "pestaña. Si no llegaste a autorizar, la pantalla caducó: volvé a tu asistente (Claude o ChatGPT) e "
                         "intentá conectar de nuevo.")
COOKIE_RECORDAR = "agentika_recuerdo"
AUD_RECORDAR = "agentika-recordar"
VIGENCIA_RECORDAR = timedelta(days=90)
AVISO_PRIVACIDAD = (
    "Qué se guarda: la huella (hash) de tu código de invitado, un contador de cuántas búsquedas hacés y, por cada llamada, la "
    "herramienta, la hora, la duración y cuántos resultados salieron. También se guarda, durante 90 días, el texto de tus búsquedas "
    "y de las frases que verificás, junto con los filtros y los fallos que pediste; solo lo ve quien administra "
    f"{NOMBRE_PRODUCTO}, para entender el uso y mejorar el servicio, y se borra solo a los 90 días. Para buscar por significado, el "
    "texto de la consulta se envía a Voyage AI (Estados Unidos), con la opción de no retención ni entrenamiento activada. Si el "
    "asistente usa la herramienta de reportes, ese reporte sí se guarda. Si tocás el enlace a aientika.ai que trae una respuesta, "
    "se anota esa visita junto con la búsqueda que la originó.")
AVISO_DESKTOP = ("Con Claude Desktop, escribí el código enseguida (en menos de 2 minutos): si tarda más, Desktop deja de esperar "
                 "y hay que volver a empezar desde Desktop.")
_ESTILO = ("body{font-family:system-ui,sans-serif;max-width:30rem;margin:2rem auto;padding:0 1rem;color:#1a1a1a}"
           "input{width:100%;font:1.1rem ui-monospace,monospace;padding:.6rem;margin:.4rem 0 1rem;box-sizing:border-box}"
           "button{font-size:1rem;padding:.6rem 1.2rem;margin-right:.5rem}.error{color:#a00;margin:1rem 0}"
           ".chico{color:#555;font-size:.85rem}")


def _pagina(cuerpo: str, status: int = 200, cabeza: str = "") -> HTMLResponse:
    html_ = (f"<!doctype html><html lang='es'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
             f"{cabeza}<title>Conectar con {NOMBRE_PRODUCTO}</title><style>{_ESTILO}{pantalla_listo.ESTILO}</style></head><body>{cuerpo}"
             f"<p class='chico' style='margin-top:2rem'><a href='{SITIO_AUTOR}' rel='noopener'>"
             f"{html.escape(CONSTRUIDO_POR)}</a></p></body></html>")
    return HTMLResponse(html_, status_code=status, headers={
        "Cache-Control": "no-store", "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer",
        "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'"})


def _error(mensaje: str, status: int) -> HTMLResponse:
    return _pagina(f"<p class='error'>{html.escape(mensaje)}</p>", status)


def _formulario(s: str, nonce: str, etiqueta: str, retorno: str, error: str | None = None, status: int = 200,
                seguro: bool = True, recordado: str | None = None) -> HTMLResponse:
    # Retorno local = Claude Desktop con mcp-remote: su receptor espera poco.
    extra = {"claude": "<p class='chico'>En el plan gratuito de Claude se permite un solo conector personalizado.</p>",
             "chatgpt": "", "local": f"<p class='chico'>{html.escape(AVISO_DESKTOP)}</p>"}[retorno]
    err = f"<p class='error'>{html.escape(error)}</p>" if error else ""
    cuerpo = (f"<h1 style='font-size:1.25rem'>{html.escape(etiqueta)} quiere conectarse a {NOMBRE_PRODUCTO}</h1>"
              f"<p>La autorización dura 90 días. Si no iniciaste esto desde tu asistente (Claude o ChatGPT), cancelá.</p>{extra}{err}"
              f"<form method='POST' action='{RUTA_PANTALLA}'><input type='hidden' name='s' value='{html.escape(s)}'>"
              f"<input type='hidden' name='nonce' value='{html.escape(nonce)}'>"
              + (f"<p>Este equipo te recuerda como <b>{html.escape(recordado)}</b>: no hace falta el código.</p>"
                 "<button type='submit' name='accion' value='autorizar'>Autorizar</button>"
                 "<button type='submit' name='accion' value='cancelar' formnovalidate>Cancelar</button>"
                 "<button type='submit' name='accion' value='olvidar' formnovalidate>Usar otro código</button></form>"
                 if recordado else
                 "<label for='codigo'>Tu código de invitado</label>"
                 "<input type='text' id='codigo' name='codigo' required autofocus autocomplete='off' autocapitalize='characters' "
                 "maxlength='32'><label class='chico'><input type='checkbox' name='recordar' value='1' style='width:auto'> "
                 "Recordarme en este equipo (90 días). No lo marques en una computadora compartida.</label><br><br>"
                 "<button type='submit' name='accion' value='autorizar'>Autorizar</button>"
                 "<button type='submit' name='accion' value='cancelar' formnovalidate>Cancelar</button></form>")
              + f"<p class='chico'>{html.escape(AVISO_PRIVACIDAD)}</p>")
    resp = _pagina(cuerpo, status)
    resp.set_cookie(COOKIE_NONCE, nonce, max_age=600, httponly=True, secure=seguro, samesite="lax", path=RUTA_PANTALLA)
    return resp


def ip_confiable(request: Request) -> str:
    """IP del cliente: la ÚLTIMA entrada de X-Forwarded-For (la agrega Google Front End; las anteriores las puede inventar quien llama)."""
    xff = request.headers.get("x-forwarded-for", "")
    ultimo = xff.split(",")[-1].strip() if xff else ""
    return ultimo or (request.client.host if request.client else "desconocida")


class Pantalla:
    """Las dos rutas de la pantalla, con `reloj` y `url_publica` inyectados."""

    def __init__(self, url_publica: str, reloj=lambda: datetime.now(timezone.utc)):
        self.reloj = reloj
        self.seguro = url_publica.startswith("https://")

    def _etiqueta(self, client_id: str) -> str:
        with bd.estado() as conn:
            cur = conn.cursor()
            cur.execute("SELECT etiqueta FROM oauth_cliente WHERE client_id = %s", (client_id,))
            fila = cur.fetchone()
        return fila[0] if fila else "Tu asistente"

    def _recordado(self, request: Request) -> tuple[str, str] | None:
        """(id, etiqueta) del invitado que este equipo recuerda, si la cookie es válida y el invitado sigue activo."""
        firmado = request.cookies.get(COOKIE_RECORDAR, "")
        if not firmado:
            return None
        try:
            id_ = str(solicitud.leer(firmado, aud=AUD_RECORDAR)["inv"])
        except (solicitud.SolicitudInvalida, KeyError):
            return None
        with bd.estado() as conn:
            etiqueta = invitados.etiqueta_activa(conn.cursor(), id_)
        return (id_, etiqueta) if etiqueta else None

    def _recordar(self, resp, invitado: str, ahora: datetime):
        """Fija la cookie de «recordarme»: solo el id del invitado, firmado, por 90 días."""
        firmado = solicitud.firmar({"inv": invitado}, aud=AUD_RECORDAR, ahora=ahora, vigencia=VIGENCIA_RECORDAR)
        resp.set_cookie(COOKIE_RECORDAR, firmado, max_age=int(VIGENCIA_RECORDAR.total_seconds()), httponly=True,
                        secure=self.seguro, samesite="lax", path=RUTA_PANTALLA)

    async def get(self, request: Request) -> HTMLResponse:
        """GET: muestra el formulario de una solicitud vigente y fija el nonce en la cookie."""
        import asyncio
        if limites.fuera_de_horario(self.reloj()):
            return _error(limites.MENSAJE_FUERA_DE_HORARIO, 503)
        s = request.query_params.get("s", "")
        if not s:  # recarga de la pantalla después de autorizar (el retorno ya se llevó la solicitud): no es un error
            return _error(MENSAJE_YA_AUTORIZADO, 400)
        try:
            sol = solicitud.leer(s)
            etiqueta = await asyncio.to_thread(self._etiqueta, sol["client_id"])
            recordado = await asyncio.to_thread(self._recordado, request)
        except solicitud.SolicitudInvalida:
            return _error("Esta solicitud venció o no es válida. Volvé a tu asistente (Claude o ChatGPT) e intentá agregar el conector de nuevo.", 400)
        except bd.BDNoDisponible:
            return _error(bd.MENSAJE_NO_DISPONIBLE, 503)
        return _formulario(s, secrets.token_urlsafe(24), etiqueta, tipo_retorno(sol["redirect_uri"]), seguro=self.seguro,
                           recordado=recordado[1] if recordado else None)

    async def post(self, request: Request) -> HTMLResponse | RedirectResponse:
        """POST: valida solicitud, nonce y código; devuelve a Claude con el código de autorización, o la pantalla con el motivo."""
        import asyncio
        ahora = self.reloj()
        if limites.fuera_de_horario(ahora):
            return _error(limites.MENSAJE_FUERA_DE_HORARIO, 503)
        campos = await request.form()
        s, nonce = str(campos.get("s", "")), str(campos.get("nonce", ""))
        try:
            sol = solicitud.leer(s)
        except solicitud.SolicitudInvalida:
            return _error("Esta solicitud venció. Volvé a tu asistente e intentá de nuevo.", 400)
        esperado = request.cookies.get(COOKIE_NONCE, "")
        if not esperado or not secrets.compare_digest(esperado, nonce):  # también: reenvío del formulario después de autorizar
            return _error(MENSAJE_YA_AUTORIZADO, 400)
        if campos.get("accion") == "cancelar":
            resp = RedirectResponse(construct_redirect_uri(sol["redirect_uri"], error="access_denied", state=sol["state"]), 303)
            resp.delete_cookie(COOKIE_NONCE, path=RUTA_PANTALLA)
            return resp
        try:
            if campos.get("accion") == "olvidar":  # «Usar otro código»: borra el recuerdo y muestra el formulario con código
                etiqueta = await asyncio.to_thread(self._etiqueta, sol["client_id"])
                resp = _formulario(s, nonce, etiqueta, tipo_retorno(sol["redirect_uri"]), seguro=self.seguro)
                resp.delete_cookie(COOKIE_RECORDAR, path=RUTA_PANTALLA)
                return resp
            codigo = str(campos.get("codigo", ""))
            recordado = None if codigo.strip() else await asyncio.to_thread(self._recordado, request)
            return await asyncio.to_thread(self._autorizar, sol, s, nonce, codigo, ahora, ip_confiable(request),
                                           campos.get("recordar") == "1", recordado[0] if recordado else None)
        except bd.BDNoDisponible:
            return _error(bd.MENSAJE_NO_DISPONIBLE, 503)

    def _autorizar(self, sol: dict, s: str, nonce: str, codigo: str, ahora: datetime, ip: str, recordar: bool = False,
                   invitado_recordado: str | None = None):
        """Cuenta el intento, busca al invitado y emite el código. Síncrono: corre en un hilo."""
        ventana = f"{ahora:%Y-%m-%dT%H}:{ahora.minute // 15}"
        with bd.estado() as conn:
            cur = conn.cursor()
            # Contar ANTES de mirar el código: quien adivina gasta intentos aunque falle.
            # El contador global solo se toma si el de la IP pasó: una IP ya bloqueada no puede agotar el global y dejar a todos
            # afuera. El hash evita guardar la IP en claro, como en el registro de clientes.
            ok_ip = limites.tomar(cur, f"intento-ip:{hash_ip(ip)}", ventana, INTENTOS_POR_IP)
            ok_global = ok_ip and limites.tomar(cur, "intento-global", f"h:{ahora:%Y-%m-%dT%H}", INTENTOS_GLOBALES_HORA)
            if not (ok_ip and ok_global):
                return _error("Demasiados intentos. Esperá 15 minutos y volvé a probar.", 429)
            if invitados.normalizar(codigo):
                invitado = invitados.buscar_por_codigo(cur, codigo)
            else:  # sin código: solo vale el invitado que este equipo recuerda, ya validado activo en `_recordado`
                invitado = invitado_recordado
        etiqueta = self._etiqueta(sol["client_id"])
        if invitado is None:
            return _formulario(s, nonce, etiqueta, tipo_retorno(sol["redirect_uri"]), "Código de invitado inválido.", 401, self.seguro)
        code = emitir_codigo(sol["client_id"], invitado, sol, ahora, AVISO_VERSION)  # el aviso que se mostró con este formulario
        # «código emitido» sin «autorizado» después significa que el cliente no canjeó el código: sirve para diagnosticarlo.
        # El log no lleva el código ni el invitado, y el client_id va truncado.
        logger.info("[conector-oauth] codigo emitido cliente=%s retorno=%s", sol["client_id"][:8],
                    "local" if tipo_retorno(sol["redirect_uri"]) == "local" else "web")
        url = construct_redirect_uri(sol["redirect_uri"], code=code, state=sol["state"])
        retorno = tipo_retorno(sol["redirect_uri"])
        if retorno == "local":  # Claude Desktop: su receptor espera poco, vuelve enseguida
            resp = RedirectResponse(url, 303)
        else:  # pantalla «Listo» con la primera consulta y la señal de que funcionó; vuelve sola (pantalla_listo.py)
            meta, texto = pantalla_listo.cuerpo(retorno, url)
            resp = _pagina(texto, cabeza=meta)
        resp.delete_cookie(COOKIE_NONCE, path=RUTA_PANTALLA)
        if recordar and invitados.normalizar(codigo):  # se recuerda solo a quien acaba de probar su código
            self._recordar(resp, invitado, ahora)
        return resp
