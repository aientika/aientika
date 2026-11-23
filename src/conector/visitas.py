"""Registro de las visitas al sitio de Aiéntika que llegan desde Claude o ChatGPT.

La página del sitio (`analitica.js`) pide `GET /visita?o=<origen>&p=<página>[&r=<referencia>]` al conector cuando la visita viene de
un asistente (marca `utm_source` de la tarjeta o referente claude.ai / chatgpt.com). Siempre deja una línea en el registro del
servicio con el origen y la página.

Si trae una referencia válida (`referencia_visita`), además anota la visita en `conector_llamada` como
herramienta `visita_sitio` con el invitado: así se une a quién la hizo y, por la hora, a la búsqueda que la originó.
Ni la referencia ni el invitado van al registro del servicio.

La IP: el código no la escribe. La plataforma guarda por su cuenta el registro HTTP de cada pedido (URL con la referencia cifrada,
IP y navegador); para `/visita` ese registro se descarta con un filtro de exclusión.
"""

from __future__ import annotations

import logging
import re
import time

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import Response

from src.conector import referencia_visita, registro

RUTA = "/visita"
ORIGENES = ("claude", "chatgpt", "otro")
MARCA = "visita_sitio"  # el informe filtra por esta palabra
_registro = logging.getLogger(__name__)


def normalizar(origen: str | None, pagina: str | None) -> tuple[str, str]:
    """(origen permitido, ruta de la página acotada). Nada que venga de afuera se escribe sin limpiar."""
    o = (origen or "").strip().lower()
    o = o if o in ORIGENES else "otro"
    p = re.sub(r"[^A-Za-z0-9/._-]", "", (pagina or "/"))[:60] or "/"
    return o, p


PREFIJO_BUSQUEDA = "busqueda:"  # `resultado` de la fila: la hora de la búsqueda que trajo el enlace, para unirla en el informe


def anotar_unida(invitado: str, ts_busqueda: int, origen: str, pagina: str, ahora: int) -> None:
    """La visita en `conector_llamada`: herramienta `visita_sitio`, resultado = «busqueda:<hora>», vía = origen, cliente = página.
    No propaga errores (registrar)."""
    registro.registrar(ahora, invitado, MARCA, f"{PREFIJO_BUSQUEDA}{ts_busqueda}", via=origen, cliente=pagina)


async def visita(request: Request) -> Response:
    """Cuenta una visita y responde 204 sin cuerpo (lo pide una imagen de 1 píxel desde el sitio)."""
    o, p = normalizar(request.query_params.get("o"), request.query_params.get("p"))
    _registro.info("%s origen=%s pagina=%s", MARCA, o, p)
    ahora = int(time.time())
    abierta = referencia_visita.abrir(request.query_params.get("r"), ahora)
    if abierta:
        await run_in_threadpool(anotar_unida, abierta[0], abierta[1], o, p, ahora)
    return Response(status_code=204, headers={"Cache-Control": "no-store", "Access-Control-Allow-Origin": "https://alejoherrera.com"})
