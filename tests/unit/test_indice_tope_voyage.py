"""Tope duro mensual de gasto en Voyage (libro de gasto con reservas atómicas) y exigencia del opt-out, con controles."""

import datetime as dt
import json
from types import SimpleNamespace

import pytest

from src.apoyo.almacen_minimo import PrecondicionFallida
from src.indice import tope_voyage as T

AHORA = lambda: dt.datetime(2026, 11, 7, 21, 0, tzinfo=dt.timezone.utc)  # noqa: E731


class Objetos:
    """Almacén falso con semántica de generación (0 = no existe)."""

    def __init__(self, choques=0):
        self.datos, self.choques = {}, choques

    def leer(self, ruta):
        if ruta not in self.datos:
            return None
        b, g = self.datos[ruta]
        return b, SimpleNamespace(generacion=g)

    def escribir(self, ruta, datos, generacion):
        actual = self.datos.get(ruta, (None, 0))[1]
        if self.choques:
            self.choques -= 1
            self.datos[ruta] = (self.datos.get(ruta, (json.dumps({"usd": 0.0, "tokens": 0}).encode(), 0))[0], actual + 1)
            raise PrecondicionFallida("otro proceso")
        if generacion != actual:
            raise PrecondicionFallida("generación vieja")
        self.datos[ruta] = (datos, actual + 1)

    def usd(self, mes="2026-11"):
        return json.loads(self.datos[f"{T.PREFIJO}/{mes}.json"][0])["usd"]


@pytest.fixture(autouse=True)
def opt_out(monkeypatch):
    monkeypatch.setenv("VOYAGE_OPT_OUT_CONFIRMADO", "2026-11-07")


def test_sin_opt_out_no_se_reserva_nada(monkeypatch):
    monkeypatch.delenv("VOYAGE_OPT_OUT_CONFIRMADO")
    o = Objetos()
    with pytest.raises(T.SinOptOut):
        T.TopeVoyage(o, AHORA).reservar("voyage-4", ["texto"])
    assert o.datos == {}


def test_reserva_y_ajuste_con_tokens_reales():
    o = Objetos()
    tope = T.TopeVoyage(o, AHORA)
    r = tope.reservar("voyage-4", ["x" * 2500])  # cota: 1.008 tokens
    assert r.tokens == 1008 and r.mes == "2026-11"
    tope.ajustar(r, 700)
    assert o.usd() == pytest.approx(700 * 0.06 / 1e6)


def test_el_tope_corta_antes_de_llamar():
    o = Objetos()
    tope = T.TopeVoyage(o, AHORA, tope_usd=0.001)
    tope.reservar("voyage-4", ["x" * 25_000])  # ≈ 10.008 tokens: cabe bajo el tope
    with pytest.raises(T.TopeAlcanzado):
        tope.reservar("voyage-4", ["x" * 25_000])  # la segunda lo pasaría
    assert o.usd() <= 0.001  # control: el libro nunca supera el tope


def test_justo_por_debajo_del_tope_pasa():
    o = Objetos()
    tope = T.TopeVoyage(o, AHORA, tope_usd=20.0)
    tope.reservar("voyage-4", ["x" * 1000])
    assert o.usd() < 20.0  # control negativo: una petición chica no se bloquea


def test_liberar_devuelve_la_reserva():
    o = Objetos()
    tope = T.TopeVoyage(o, AHORA)
    tope.liberar(tope.reservar("voyage-law-2", ["abc" * 100]))
    assert o.usd() == 0.0


def test_reintenta_si_otro_proceso_escribio_en_el_medio():
    o = Objetos(choques=2)
    T.TopeVoyage(o, AHORA).reservar("voyage-4", ["texto"])
    assert o.usd() > 0


def test_modelo_sin_precio_falla_ruidosamente():
    with pytest.raises(ValueError):
        T.costo("modelo-inventado", 10)


class ObjetosQueSeMueven(Objetos):
    """La generación que se acaba de describir desaparece antes de leerla (otro proceso escribió): error real de la herramienta de almacenamiento."""

    def __init__(self, fallas, mensaje):
        super().__init__()
        self.fallas, self.mensaje = fallas, mensaje

    def leer(self, ruta):
        if self.fallas:
            self.fallas -= 1
            raise RuntimeError(self.mensaje)
        return super().leer(ruta)


def test_generacion_que_desaparece_al_leer_se_reintenta(monkeypatch):
    monkeypatch.setattr(T.time, "sleep", lambda s: None)
    msg = "leer el libro de gasto: el objeto ya no existe (404 not found)"  # el objeto desapareció entre dos lecturas
    o = ObjetosQueSeMueven(3, msg)
    T.TopeVoyage(o, AHORA).reservar("voyage-4", ["x" * 2500])
    assert o.usd() > 0  # tras releer, la reserva quedó escrita


def test_otro_error_al_leer_no_se_disimula(monkeypatch):
    monkeypatch.setattr(T.time, "sleep", lambda s: None)
    o = ObjetosQueSeMueven(1, "leer el libro de gasto: 403 sin permiso de lectura")
    with pytest.raises(RuntimeError, match="403"):  # control: un permiso denegado no es un choque entre procesos
        T.TopeVoyage(o, AHORA).reservar("voyage-4", ["x"])


class Contador(Objetos):
    def __init__(self):
        super().__init__()
        self.escrituras = 0

    def escribir(self, ruta, datos, generacion):
        self.escrituras += 1
        super().escribir(ruta, datos, generacion)


def test_cupo_escribe_mucho_menos_y_al_cerrar_queda_el_gasto_real():
    o = Contador()
    tope = T.TopeVoyage(o, AHORA, cuota_usd=0.25)
    for _ in range(50):  # 50 peticiones de ≈ 4.000 tokens reservados y 1.000 reales
        r = tope.reservar("voyage-4", ["x" * 10_000])
        tope.ajustar(r, 1000)
    assert o.escrituras <= 3  # sin cupo serían 100
    tope.cerrar()
    assert o.usd() == pytest.approx(50 * 1000 * 0.06 / 1e6)  # al cerrar queda exactamente lo gastado
    assert json.loads(o.datos[f"{T.PREFIJO}/2026-11.json"][0])["tokens"] == 50_000


def test_cupo_respeta_el_tope_duro():
    o = Objetos()
    casi = T.tope_embebido("2026-11") - 0.1
    o.datos[f"{T.PREFIJO}/2026-11.json"] = (json.dumps({"usd": casi, "tokens": 0}).encode(), 1)
    tope = T.TopeVoyage(o, AHORA, cuota_usd=0.25)
    with pytest.raises(T.TopeAlcanzado):  # el cupo de 0,25 pasaría el corte del embebido: no se reserva y no se llama
        tope.reservar("voyage-4", ["x" * 100])
    assert o.usd() == pytest.approx(casi)


def test_cupo_liberado_y_exceso_anotado_al_momento():
    o = Objetos()
    tope = T.TopeVoyage(o, AHORA, cuota_usd=0.25)
    r = tope.reservar("voyage-4", ["x" * 100])
    tope.liberar(r)
    tope.cerrar()
    assert o.usd() == pytest.approx(0.0)  # control: una petición fallida no deja gasto
    tope2 = T.TopeVoyage(o, AHORA, cuota_usd=0.000001)
    r2 = tope2.reservar("voyage-4", ["x"])
    tope2.ajustar(r2, 10_000_000)  # Voyage cobró mucho más de lo reservado: se anota ya, no al cierre
    assert o.usd() >= 10_000_000 * 0.06 / 1e6 - 1e-6


def test_el_tope_por_defecto_no_cambia_sin_una_decision_explicita():
    # Este test existe para que el tope no cambie sin que alguien lo decida: si se cambia, se actualiza aquí.
    assert T.TOPE_USD == 10.0


def test_la_excepcion_por_mes_manda_y_los_demas_meses_usan_el_tope_por_defecto(monkeypatch):
    monkeypatch.setitem(T.TOPE_USD_POR_MES, "2026-11", 25.0)
    monkeypatch.setitem(T.TOPE_USD_POR_MES, "2026-12", 25.0)
    assert T.tope_cuenta("2026-11") == T.tope_cuenta("2026-12") == 25.0
    assert T.tope_cuenta("2027-01") == T.tope_cuenta("2026-10") == T.TOPE_USD == 10.0
    assert T.tope_embebido("2026-12") == 25.0 - T.RESERVA_CONSULTAS_USD


def test_el_tope_de_enero_corta_lo_que_diciembre_dejaba_pasar(monkeypatch):
    monkeypatch.setenv("VOYAGE_OPT_OUT_CONFIRMADO", "2026-11-07")
    monkeypatch.setitem(T.TOPE_USD_POR_MES, "2026-12", 25.0)
    import datetime as dt
    for mes, ahora, corta in (("2026-12", dt.datetime(2026, 12, 15, tzinfo=dt.timezone.utc), False),
                              ("2027-01", dt.datetime(2027, 1, 15, tzinfo=dt.timezone.utc), True)):
        o = Objetos()
        o.datos[f"{T.PREFIJO}/{mes}.json"] = (json.dumps({"usd": 15.0, "tokens": 0}).encode(), 1)
        tope = T.TopeVoyage(o, lambda a=ahora: a)
        if corta:
            with pytest.raises(T.TopeAlcanzado):
                tope.reservar("voyage-4", ["x" * 100])
        else:
            tope.reservar("voyage-4", ["x" * 100])  # control positivo: 15 está bajo el tope de diciembre (25) y sobre el de enero (10)
