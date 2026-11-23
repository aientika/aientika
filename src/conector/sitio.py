"""La página pública de Aiéntika en la raíz de aientika.ai.

`GET /` devuelve `sitio/index.html` y `GET /sitio/<archivo>` sus recursos, solo los de una lista fija leída al importar (nada de listar
carpetas ni de seguir `..`). No toca la base: responde igual con la base no disponible. Los videos no
viajan en la imagen: se sirven desde un CDN externo.

CSP propia, más abierta que la de las pantallas de autorización (que no permiten scripts): scripts solo del mismo origen y de Google
Analytics; nada en línea.
"""

from __future__ import annotations

import hashlib
import mimetypes
import re
from pathlib import Path

from starlette.requests import Request
from starlette.responses import Response

CARPETA = Path(__file__).resolve().parent / "sitio"
RUTA_INICIO = "/"
PREFIJO = "/sitio/"
RUTA_RECURSOS = PREFIJO + "{archivo:path}"
_GOOGLE = "https://www.googletagmanager.com https://*.google-analytics.com https://*.analytics.google.com"
CSP = ("default-src 'self'; "
       f"script-src 'self' https://www.googletagmanager.com; "
       f"connect-src 'self' {_GOOGLE}; "
       f"img-src 'self' data: https://alejoherrera.com {_GOOGLE}; "
       "media-src https://alejoherrera.com; style-src 'self'; font-src 'self'; "
       "frame-ancestors 'none'; base-uri 'none'; form-action 'none'; object-src 'none'")
_TIPOS = {".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".woff2": "font/woff2",
          ".jpg": "image/jpeg", ".html": "text/html; charset=utf-8"}


def _cargar() -> dict[str, tuple[bytes, str]]:
    """{ruta relativa con «/»: (bytes, tipo)} de todos los archivos de la carpeta, leídos una vez."""
    archivos = {}
    for p in sorted(CARPETA.rglob("*")):
        if p.is_file():
            tipo = _TIPOS.get(p.suffix.lower()) or mimetypes.guess_type(p.name)[0] or "application/octet-stream"
            archivos[p.relative_to(CARPETA).as_posix()] = (p.read_bytes(), tipo)
    if "index.html" not in archivos:
        raise RuntimeError(f"falta {CARPETA / 'index.html'}: armar el sitio")
    # Cada «/sitio/<archivo>» de la página lleva «?v=<huella>» de su contenido: los recursos se guardan un día en el navegador, y sin
    # esto una página nueva se veía con el CSS viejo.
    def con_huella(m: re.Match) -> bytes:
        nombre = m.group(1).decode()
        if nombre not in archivos:
            raise RuntimeError(f"index.html pide /sitio/{nombre}, que no existe")
        return b'"/sitio/' + m.group(1) + b"?v=" + hashlib.sha256(archivos[nombre][0]).hexdigest()[:10].encode() + b'"'
    cuerpo, tipo = archivos["index.html"]
    archivos["index.html"] = (re.sub(rb'"/sitio/([^"?#]+)"', con_huella, cuerpo), tipo)
    return archivos


ARCHIVOS = _cargar()


def _cabeceras(tipo: str, max_age: int) -> dict[str, str]:
    return {"Content-Type": tipo, "Cache-Control": f"public, max-age={max_age}", "Content-Security-Policy": CSP,
            "X-Content-Type-Options": "nosniff", "Referrer-Policy": "strict-origin-when-cross-origin"}


async def inicio(request: Request) -> Response:
    """La página de Aiéntika."""
    cuerpo, tipo = ARCHIVOS["index.html"]
    return Response(cuerpo, headers=_cabeceras(tipo, 300))


async def recurso(request: Request) -> Response:
    """Un archivo de la lista fija, o 404. La página misma no se sirve por acá (una sola dirección: `/`)."""
    nombre = request.path_params.get("archivo", "")
    if nombre == "index.html" or nombre not in ARCHIVOS:
        return Response("No encontrado", status_code=404, headers={"Content-Type": "text/plain; charset=utf-8"})
    cuerpo, tipo = ARCHIVOS[nombre]
    return Response(cuerpo, headers=_cabeceras(tipo, 86400))
