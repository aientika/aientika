"""Tope DURO de gasto en Voyage: no pasar del techo mensual (calendario UTC), sumando embebido y consultas del conector.

Este libro solo ve el embebido: el techo menos la reserva (`TOPE_EMBEBIDO_USD`). Las consultas del conector llevan su propio libro en
Postgres, limitado a una reserva (`RESERVA_CONSULTAS_USD`): embebido + reserva = el techo de la cuenta.

El techo mensual es configurable por mes (`TOPE_USD_POR_MES`); en los meses sin excepción rige `TOPE_USD`.

El proveedor solo ofrece alertas por correo, no un corte, así que el corte vive aquí: antes de cada llamada se RESERVA el costo
máximo posible en el libro de gasto del índice (escritura condicionada, para que dos procesos no se pisen) y, si la reserva
pasaría el tope, la llamada no se hace. Después se ajusta con los tokens reales.
Se supone que el cupo gratuito NO existe: el opt-out puede anularlo.
Además exige la constancia del opt-out (`VOYAGE_OPT_OUT_CONFIRMADO`): sin ella no se envía nada a Voyage.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import random
import time
from dataclasses import dataclass

from src.apoyo.almacen_minimo import _NO_EXISTE, PrecondicionFallida

TOPE_USD = 10.0  # techo de la CUENTA de Voyage por mes: embebido de documentos + consultas del conector, juntos
RESERVA_CONSULTAS_USD = 1.0  # parte del techo reservada a las consultas del conector (su libro vive en Postgres, no aquí)
TOPE_EMBEBIDO_USD = TOPE_USD - RESERVA_CONSULTAS_USD  # lo que `TopeVoyage` deja gastar al embebido: así la suma nunca pasa de TOPE_USD
# Excepciones al techo, por mes.
TOPE_USD_POR_MES: dict[str, float] = {}


def tope_cuenta(mes: str) -> float:
    """Techo de la cuenta de Voyage en el mes `AAAA-MM`: la excepción del mes, si la hay, o `TOPE_USD`."""
    return TOPE_USD_POR_MES.get(mes, TOPE_USD)


def tope_embebido(mes: str) -> float:
    """Lo que el embebido puede gastar en el mes: el techo menos la reserva de las consultas del conector."""
    return tope_cuenta(mes) - RESERVA_CONSULTAS_USD
PRECIO_POR_MILLON = {"voyage-4": 0.06, "voyage-law-2": 0.12}  # docs.voyageai.com/docs/pricing
CARACTERES_POR_TOKEN_MIN = 2.5  # cota pesimista para reservar: más tokens de los que habrá
PREFIJO = "indice/voyage_gasto"
INTENTOS = 25  # con varios procesos a la vez los choques son frecuentes; cada intento espera al azar


class TopeAlcanzado(RuntimeError):
    """La llamada haría pasar el gasto del mes de TOPE_USD: no se hace."""


class SinOptOut(RuntimeError):
    """No hay constancia del opt-out de entrenamiento: no se envía nada a Voyage."""


def exigir_opt_out() -> str:
    """Devuelve la constancia (fecha del opt-out) o lanza SinOptOut."""
    valor = os.environ.get("VOYAGE_OPT_OUT_CONFIRMADO", "").strip()
    if not valor:
        raise SinOptOut("falta VOYAGE_OPT_OUT_CONFIRMADO: el opt-out de Voyage no está registrado")
    return valor


def costo(modelo: str, tokens: int) -> float:
    if modelo not in PRECIO_POR_MILLON:
        raise ValueError(f"modelo sin precio registrado: {modelo}")
    return tokens * PRECIO_POR_MILLON[modelo] / 1_000_000


def tokens_maximos(textos: list[str]) -> int:
    """Cota superior de tokens de una petición, para reservar."""
    return sum(int(len(t) / CARACTERES_POR_TOKEN_MIN) + 8 for t in textos)


@dataclass
class Reserva:
    mes: str
    modelo: str
    tokens: int


class TopeVoyage:
    """Libro mensual de gasto con reservas atómicas. `objetos` ofrece leer y escribir de forma condicionada.

    Con `cuota_usd > 0` el proceso reserva en el libro un CUPO de una vez y lo gasta localmente; vuelve al libro solo
    cuando se le acaba, y `cerrar` devuelve lo no usado y anota los tokens reales. Existe porque con varios procesos
    anotando en cada lote el libro sufre demasiados choques y no logra escribirse. El tope sigue duro: el cupo se descuenta ANTES de
    gastar. Si el proceso muere, su cupo sin usar queda contado como gasto (error conservador, como mucho `cuota_usd` por caída).
    """

    def __init__(self, objetos, ahora=lambda: dt.datetime.now(dt.timezone.utc), tope_usd: float | None = None,
                 cuota_usd: float = 0.0):
        # Sin `tope_usd`, el tope sale del mes de cada anotación (`tope_embebido`), así cambia solo al pasar de mes.
        self.objetos, self.ahora, self.tope, self.cuota = objetos, ahora, tope_usd, cuota_usd
        self.saldo, self.mes_saldo, self.tokens_pendientes, self.ultimo = 0.0, None, 0, {}

    def tope_del_mes(self, mes: str) -> float:
        """El tope que rige para `mes`: el explícito del constructor, o el del calendario."""
        return self.tope if self.tope is not None else tope_embebido(mes)

    def _ruta(self, mes: str) -> str:
        return f"{PREFIJO}/{mes}.json"

    def _mover(self, mes: str, modelo: str, tokens: int, comprobar: bool) -> dict:
        return self._mover_usd(mes, costo(modelo, tokens), tokens, comprobar)

    def _mover_usd(self, mes: str, delta_usd: float, delta_tokens: int, comprobar: bool) -> dict:
        for _ in range(INTENTOS):
            try:
                leido = self.objetos.leer(self._ruta(mes))
            except RuntimeError as exc:
                # `leer` consulta el estado y después pide ESA versión. Si otro proceso escribió en el medio, esa versión
                # ya no existe: es el mismo conflicto que una precondición fallida.
                if _NO_EXISTE.search(str(exc)):
                    time.sleep(random.uniform(0.2, 1.5))
                    continue
                raise
            libro, gen = (json.loads(leido[0]), leido[1].generacion) if leido else ({"usd": 0.0, "tokens": 0}, 0)
            nuevo = round(libro["usd"] + delta_usd, 6)
            tope = self.tope_del_mes(mes)
            if comprobar and nuevo > tope:
                raise TopeAlcanzado(f"gasto de Voyage en {mes}: US${libro['usd']:.2f}; esta petición lo llevaría a "
                                    f"US${nuevo:.2f}, por encima del tope de US${tope:.2f}")
            libro = {"usd": max(nuevo, 0.0), "tokens": max(libro["tokens"] + delta_tokens, 0)}
            try:
                self.objetos.escribir(self._ruta(mes), json.dumps(libro).encode("utf-8"), generacion=gen)
                self.ultimo = libro
                return libro
            except PrecondicionFallida:
                time.sleep(random.uniform(0.2, 1.5))
                continue  # otro proceso escribió en el medio: se relee y se vuelve a calcular
        raise RuntimeError(f"no se pudo actualizar el libro de gasto de {mes} tras {INTENTOS} intentos")

    def reservar(self, modelo: str, textos: list[str]) -> Reserva:
        """Reserva el máximo posible ANTES de llamar. Lanza SinOptOut o TopeAlcanzado."""
        exigir_opt_out()
        mes = self.ahora().strftime("%Y-%m")
        tokens = tokens_maximos(textos)
        if not self.cuota:
            self._mover(mes, modelo, tokens, comprobar=True)
            return Reserva(mes, modelo, tokens)
        if self.mes_saldo not in (None, mes):
            self.cerrar()  # cambió el mes: el cupo del mes anterior se devuelve a su libro
        c = costo(modelo, tokens)
        if self.saldo < c:
            pedir = round(max(c, self.cuota) - self.saldo, 6)
            self._mover_usd(mes, pedir, 0, comprobar=True)
            self.saldo, self.mes_saldo = self.saldo + pedir, mes
        self.saldo -= c
        return Reserva(mes, modelo, tokens)

    def ajustar(self, reserva: Reserva, tokens_reales: int) -> dict:
        """Corrige la reserva con lo que Voyage informó (`usage.total_tokens`). Si se usó más, se suma igual."""
        if not self.cuota:
            return self._mover(reserva.mes, reserva.modelo, tokens_reales - reserva.tokens, comprobar=False)
        self.saldo += costo(reserva.modelo, reserva.tokens) - costo(reserva.modelo, tokens_reales)
        self.tokens_pendientes += tokens_reales
        if self.saldo < 0:  # se gastó más de lo reservado: el exceso se anota ya, sin esperar al cierre
            self._mover_usd(reserva.mes, -self.saldo, 0, comprobar=False)
            self.saldo = 0.0
        return self.ultimo

    def liberar(self, reserva: Reserva) -> dict:
        """La llamada falló sin consumir: se devuelve la reserva entera."""
        if not self.cuota:
            return self._mover(reserva.mes, reserva.modelo, -reserva.tokens, comprobar=False)
        self.saldo += costo(reserva.modelo, reserva.tokens)
        return self.ultimo

    def cerrar(self) -> dict:
        """Devuelve al libro el cupo no usado y anota los tokens reales. Sin cupo, no hace nada."""
        if not self.cuota or self.mes_saldo is None:
            return self.ultimo
        libro = self._mover_usd(self.mes_saldo, -self.saldo, self.tokens_pendientes, comprobar=False)
        self.saldo, self.tokens_pendientes, self.mes_saldo = 0.0, 0, None
        return libro
