"""Pantalla «Listo» después de autorizar, para facilitar la instalación al usuario común.

En vez de devolver al asistente con un 303 inmediato, se muestra cómo hacer la primera consulta y cómo saber que funcionó, y la página
vuelve sola al asistente a los `ESPERA_S` segundos (meta refresh, sin JavaScript: la CSP de la pantalla no permite scripts), con un botón
para volver antes. El código de autorización vence a los 300 s (`oauth.VIGENCIA_CODIGO_S`): la espera es mucho menor.
Solo para el retorno web (Claude y ChatGPT). Claude Desktop (retorno local) sigue con el 303 inmediato: su receptor espera poco.
"""

from __future__ import annotations

import html

ESPERA_S = 10
# La pregunta de ejemplo es una de las del sitio, probada con cuentas gratuitas: lo que se ofrece funciona.
EJEMPLO = "¿qué ha dicho la Sala Constitucional sobre las listas de espera para cirugías en la CCSS?"
SENAL = "Fuente: base de Aiéntika"

# ChatGPT: el menú «@» distingue la tilde: «@aien» no encuentra «Aiéntika» y «@ai» sí (comprobado en vivo).
_COMO = {
    "claude": ("Claude",
               f"<p>Abrí un chat nuevo y empezá tu pregunta con <b>«aientika»</b>. Por ejemplo:</p>"
               f"<p class='ejemplo'>aientika, {html.escape(EJEMPLO)}</p>"
               "<p class='chico'>Recomendado: en Claude, en el conector, pasá «Herramientas de solo lectura» a <b>Permitir siempre</b>, "
               "para que no te pida aprobación en cada búsqueda.</p>"),
    "chatgpt": ("ChatGPT",
                "<p>Abrí un chat nuevo, escribí <b>@ai</b> y <b>elegí Aiéntika en el menú</b> (queda como una etiqueta azul); "
                "después escribí tu pregunta. Por ejemplo:</p>"
                f"<p class='ejemplo'>{html.escape(EJEMPLO[0].upper() + EJEMPLO[1:])}</p>"
                "<p class='chico'>Si escribís «aientika» a mano sin elegirlo del menú, a veces ChatGPT no lo consulta.</p>"),
}
# Cómo saber que funcionó. En Claude la respuesta cierra con la línea de fuente; en ChatGPT NO es confiable (a veces consulta el
# conector y termina con el enlace al sitio, sin la línea): ahí la señal es que trae fallos con su enlace oficial.
_SENAL_HTML = {
    "claude": f"<p>Sabés que funcionó si la respuesta termina con <b>«{html.escape(SENAL)}»</b>. Si no la trae, no lo consultó: "
              "volvé a preguntar.</p>",
    "chatgpt": "<p>Sabés que funcionó si tu mensaje lleva la etiqueta <b>Aiéntika</b> y la respuesta trae fallos de Costa Rica con su "
               "<b>enlace oficial</b>. Si no, volvé a preguntar eligiendo Aiéntika en el menú.</p>",
}
ESTILO = ".ejemplo{background:#f3f4f6;border-radius:.5rem;padding:.6rem .8rem;font-style:italic}.boton{display:inline-block;" \
         "background:#1a1a1a;color:#fff;padding:.6rem 1.2rem;border-radius:.4rem;text-decoration:none;margin:.5rem 0}"


def cuerpo(retorno: str, url_retorno: str) -> tuple[str, str]:
    """(meta del <head>, cuerpo) de la pantalla «Listo» para el retorno «claude» o «chatgpt»; `url_retorno` ya trae code y state."""
    nombre, como = _COMO[retorno]
    u = html.escape(url_retorno, quote=True)
    meta = f"<meta http-equiv='refresh' content='{ESPERA_S};url={u}'>"
    texto = (f"<h1 style='font-size:1.25rem'>Listo: Aiéntika quedó conectado</h1>{como}{_SENAL_HTML[retorno]}"
             f"<p><a id='volver' class='boton' href='{u}'>Volver a {nombre}</a></p>"
             f"<p class='chico'>Te llevamos a {nombre} en {ESPERA_S} segundos.</p>")
    return meta, texto
