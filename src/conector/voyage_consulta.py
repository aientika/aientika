"""Embebido de la CONSULTA del usuario con `voyage-4` (`input_type=query`) para la vía semántica de `buscar`.

Reusa `ClienteVoyage` (misma API, `User-Agent: agent`, `truncation: false`) y exige la constancia del opt-out igual que el
embebido de documentos: las consultas son lo sensible. El presupuesto vive en otra capa (Postgres): aquí `reservar(tokens)` se
INYECTA y, si nadie lo inyecta, levanta; así este módulo no puede gastar sin que algo cuente. Si Voyage está ocupado o
falla, el error sube (nunca se degrada a «cero resultados»); no se reintenta con esperas largas: es una consulta interactiva.
"""

from __future__ import annotations

import os

from src.indice.embeber_voyage import DIMENSION, ClienteVoyage, ErrorVoyage, tokens_est
from src.indice.tope_voyage import CARACTERES_POR_TOKEN_MIN, exigir_opt_out

MODELO = "voyage-4"
MAX_CARACTERES = 2000
TIEMPO_MAXIMO_S = 12  # una consulta interactiva no espera los 300 s del embebido por lotes: ocuparía un hilo del servidor


class PresupuestoNoInyectado(RuntimeError):
    """No se inyectó `reservar`: sin presupuesto que lo cuente, no se llama a Voyage."""


def reservar_no_inyectado(tokens: int) -> None:
    """Valor por defecto de `reservar`: falla, a propósito."""
    raise PresupuestoNoInyectado("falta inyectar reservar(tokens): el presupuesto de consultas lo lleva otra capa")


def _no_esperar(segundos: float) -> None:
    raise ErrorVoyage("Voyage pidió esperar (límite o saturación); la consulta no se reintenta")


def tokens_maximos(consulta: str) -> int:
    """Cota superior de tokens de la consulta (la misma regla pesimista del tope de documentos)."""
    return int(len(consulta) / CARACTERES_POR_TOKEN_MIN) + 8


def embeber_consulta(consulta: str, reservar=reservar_no_inyectado, cliente: ClienteVoyage | None = None) -> list[float]:
    """Vector `voyage-4` de 1.024 dimensiones de `consulta`. Orden: opt-out, validar, reservar, llamar.

    `reservar(tokens)` debe levantar si el presupuesto no alcanza. `cliente` se inyecta en las pruebas; por defecto usa
    `VOYAGE_API_KEY` y no espera ante 429/5xx.
    """
    exigir_opt_out()
    consulta = " ".join(consulta.split())
    if not consulta:
        raise ValueError("consulta vacía")
    if len(consulta) > MAX_CARACTERES:
        raise ValueError(f"consulta de {len(consulta)} caracteres; el máximo es {MAX_CARACTERES}")
    reservar(max(tokens_maximos(consulta), tokens_est(consulta)))
    cliente = cliente or ClienteVoyage(os.environ["VOYAGE_API_KEY"].strip(), dormir=_no_esperar, timeout=TIEMPO_MAXIMO_S)
    vectores, _tokens = cliente.embeber([consulta], MODELO, tipo="query")
    if len(vectores) != 1 or len(vectores[0]) != DIMENSION[MODELO]:
        raise ErrorVoyage(f"Voyage devolvió {len(vectores)} vectores de {len(vectores[0]) if vectores else 0} dimensiones")
    return vectores[0]
