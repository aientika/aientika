"""Presupuesto de Voyage para las CONSULTAS, en Postgres y separado del libro de gasto del índice.

El techo de la cuenta se reparte entre el libro del índice (el techo menos la reserva) y este (la reserva), así que juntos no pasan del techo
sin que un libro tenga que leer al otro.

Implementa el `reservar(tokens)` que `voyage_consulta.embeber_consulta` exige inyectado: el mismo UPSERT condicional atómico de los
límites, sobre el mes calendario UTC (así factura Voyage). Se reserva la cota pesimista de tokens ANTES de llamar, así que dos
consultas en paralelo no pueden pasar el tope. El tope sale del precio y del dólar de la constante de abajo: no se escribe a mano.
"""

from __future__ import annotations

from datetime import datetime, timezone

from src.conector import bd
from src.indice.tope_voyage import PRECIO_POR_MILLON, RESERVA_CONSULTAS_USD

MODELO = "voyage-4"
TOPE_USD_MES = RESERVA_CONSULTAS_USD  # parte del techo de la cuenta: el libro del índice deja de gastar en TOPE_USD menos la reserva
TOPE_TOKENS_MES = int(TOPE_USD_MES / PRECIO_POR_MILLON[MODELO] * 1_000_000)
UMBRAL_ALERTA = 0.8  # fracción del tope a partir de la cual conviene avisar

_UPSERT = (
    "INSERT INTO presupuesto_voyage_consultas (mes, tokens) SELECT CAST(%s AS TEXT), CAST(%s AS BIGINT) "
    "WHERE CAST(%s AS BIGINT) <= CAST(%s AS BIGINT) "
    "ON CONFLICT (mes) DO UPDATE SET tokens = presupuesto_voyage_consultas.tokens + CAST(%s AS BIGINT) "
    "WHERE presupuesto_voyage_consultas.tokens + CAST(%s AS BIGINT) <= CAST(%s AS BIGINT) RETURNING tokens"
)


class PresupuestoAgotado(RuntimeError):
    """El presupuesto mensual de consultas con Voyage no alcanza: la búsqueda por significado no se hace este mes."""


def _mes(ahora: datetime) -> str:
    return ahora.astimezone(timezone.utc).strftime("%Y-%m")


def reservar_con_reloj(reloj=lambda: datetime.now(timezone.utc)):
    """Devuelve un `reservar(tokens)` atado a `reloj` (inyectable en pruebas). Levanta PresupuestoAgotado si no alcanza."""
    def reservar(tokens: int) -> None:
        if tokens <= 0:
            raise ValueError("tokens a reservar debe ser positivo")
        with bd.estado() as conn:
            cur = conn.cursor()
            cur.execute(_UPSERT, (_mes(reloj()), tokens, tokens, TOPE_TOKENS_MES, tokens, tokens, TOPE_TOKENS_MES))
            if cur.fetchone() is None:
                raise PresupuestoAgotado("presupuesto mensual de consultas agotado")
    return reservar


reservar = reservar_con_reloj()


def fraccion_usada(ahora: datetime | None = None) -> float:
    """Parte del presupuesto del mes ya reservada (0 a 1). Sirve para avisar al pasar del 80 %."""
    ahora = ahora or datetime.now(timezone.utc)
    with bd.estado() as conn:
        cur = conn.cursor()
        cur.execute("SELECT tokens FROM presupuesto_voyage_consultas WHERE mes = %s", (_mes(ahora),))
        fila = cur.fetchone()
    return (int(fila[0]) if fila else 0) / TOPE_TOKENS_MES
