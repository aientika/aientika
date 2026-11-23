"""Cliente de embeddings (Voyage) para las consultas del conector.

Va por HTTPS directo, con `User-Agent: agent` y `truncation: false`: un texto demasiado largo es un error, nunca un recorte
silencioso del proveedor. Cada petición pasa por el tope de gasto (reserva antes, ajuste con los tokens reales después).
El armado del índice no forma parte de este repositorio.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request

URL = "https://api.voyageai.com/v1/embeddings"
DIMENSION = {"voyage-4": 1024, "voyage-law-2": 1024}
REINTENTOS = 6
CARACTERES_POR_TOKEN = 3.5  # estimación conservadora para español


class ErrorVoyage(RuntimeError):
    """Voyage respondió algo que no es un éxito ni un error transitorio: se detiene (hay que leer el cuerpo)."""


class ExcesoTokens(ErrorVoyage):
    """Voyage dice qué textos del lote pasan el límite del modelo (400 «The example at index N … too many tokens»).

    Con voyage-4, 3,5 caracteres por token es el promedio medido, pero hay extractos más densos.
    """

    def __init__(self, mensaje: str, indices: list[int]):
        super().__init__(mensaje)
        self.indices = indices


_INDICES_EXCESO = re.compile(r"examples? at (?:index|indices) ([\d,\s and]+?) in your batch", re.I)


def tokens_est(texto: str) -> int:
    return int(len(texto) / CARACTERES_POR_TOKEN) + 1


class ClienteVoyage:
    """Llamada mínima a la API de embeddings. `abrir` se inyecta en las pruebas."""

    def __init__(self, clave: str, abrir=urllib.request.urlopen, dormir=time.sleep, timeout: float = 300):
        self.clave, self.abrir, self.dormir, self.timeout = clave, abrir, dormir, timeout

    def embeber(self, textos: list[str], modelo: str, tipo: str = "document") -> tuple[list[list[float]], int]:
        cuerpo = {"input": textos, "model": modelo, "input_type": tipo, "truncation": False}
        if modelo == "voyage-4":
            cuerpo["output_dimension"] = DIMENSION[modelo]
        pedido = urllib.request.Request(URL, data=json.dumps(cuerpo).encode("utf-8"), method="POST", headers={
            "Authorization": f"Bearer {self.clave}", "Content-Type": "application/json", "User-Agent": "agent"})
        for intento in range(REINTENTOS):
            try:
                with self.abrir(pedido, timeout=self.timeout) as r:
                    datos = json.loads(r.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as exc:
                detalle = exc.read().decode("utf-8", "replace")[:400]
                if exc.code in (429, 500, 502, 503, 504) and intento < REINTENTOS - 1:
                    self.dormir(min(2 ** intento * 5, 120))
                    continue
                m = _INDICES_EXCESO.search(detalle) if exc.code == 400 and "too many tokens" in detalle else None
                if m:
                    raise ExcesoTokens(f"HTTP 400: {detalle}", [int(x) for x in re.findall(r"\d+", m.group(1))]) from exc
                raise ErrorVoyage(f"HTTP {exc.code}: {detalle}") from exc
        vectores = [d["embedding"] for d in sorted(datos["data"], key=lambda d: d["index"])]
        if len(vectores) != len(textos):
            raise ErrorVoyage(f"pedí {len(textos)} vectores y llegaron {len(vectores)}")
        return vectores, int(datos["usage"]["total_tokens"])
