"""Cobertura del conector: sale de lo que hay en la base, nunca de una cifra escrita a mano.

Los conteos imitan los de una medición real de la base: 41.103 vectores `voyage-4` solo en 2025 (61 % de lo embebible),
documentos 2022-2025, una `cargado_en` del 2026-11-10 UTC.
"""

import datetime as dt

import pytest

from src.conector import cobertura as C


class Cur:
    """Contesta por fragmento de SQL; `error` simula una BD caída."""

    def __init__(self, vectores, por_anno, elegibles, cargado, error=None):
        self.v, self.a, self.e, self.c, self.error = vectores, por_anno, elegibles, cargado, error
        self.consultas, self.rows = 0, []

    def execute(self, sql, params=()):
        if self.error:
            raise self.error
        self.consultas += 1
        if "FROM vectores" in sql:
            self.rows = [(d, a, n) for (d, a), n in self.v.items()]
        elif "count(*) FROM documentos GROUP" in sql or "SELECT anno, count(*) FROM documentos GROUP" in sql:
            self.rows = list(self.a.items())
        elif "clase_f2" in sql:
            self.rows = [(a, d, n) for (a, d), n in self.e.items()]
        else:
            self.rows = [self.c]

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0]


class Conn:
    def __init__(self, **kw):
        self.cur = Cur(**kw)

    def cursor(self):
        return self.cur


CARGADO = (dt.datetime(2026, 11, 10, 16, 3, tzinfo=dt.timezone.utc), dt.date(2025, 12, 31))


def piloto(error=None, vectores=None, elegibles=None):
    return Conn(vectores={("Sala Primera de la Corte", 2025): 4000, ("Sala Constitucional", 2025): 37103} if vectores is None
                else vectores,
                por_anno={2022: 100, 2023: 120, 2024: 130, 2025: 200}, elegibles=elegibles or {(2025, "Sala Constitucional"): 67400},
                cargado=CARGADO, error=error)


@pytest.fixture(autouse=True)
def sin_memoria():
    C._cache.clear()
    yield
    C._cache.clear()


def test_linea_declara_parcial_literal_fecha_y_que_vacio_no_prueba():
    c = C.cobertura(piloto())
    assert c["semantica"][2025]["vectores"] == 41103  # cuadra con la suma de los pares de la base
    assert c["semantica"][2025]["fraccion"] == round(41103 / 67400, 4)
    linea = c["linea"]
    assert "en las Salas en parte de 2025 (61%)" in linea and "solo búsqueda literal en 2022, 2023, 2024" in linea
    assert "Datos cargados al 2026-11-10" in linea
    assert "Un resultado vacío no prueba que no exista jurisprudencia" in linea
    assert "los años 2022, 2023, 2024, 2025" in linea
    assert c["pares_con_vectores"] == ["Sala Constitucional|2025", "Sala Primera de la Corte|2025"]


def test_anno_completo_pasa_a_semantico_y_dice_si_incluye_tribunales():
    v = {("Sala Constitucional", 2025): 60000, ("Tribunal Agrario", 2025): 7400}
    e = {(2025, "Sala Constitucional"): 60000, (2025, "Tribunal Agrario"): 7400}
    linea = C.cobertura(piloto(vectores=v, elegibles=e))["linea"]
    assert "búsqueda por significado (voyage-4) en las Salas en 2025; en los tribunales en 2025" in linea and "parte" not in linea
    C._cache.clear()
    solo_salas = C.cobertura(piloto(vectores={("Sala Constitucional", 2025): 60000}, elegibles=e))["linea"]
    assert "en las Salas en 2025; en los tribunales, solo búsqueda literal" in solo_salas


def test_sin_vectores_todo_es_literal():
    c = C.cobertura(piloto(vectores={}))
    assert c["semantica"] == {} and "búsqueda por significado" not in c["linea"]
    assert "solo búsqueda literal en 2022, 2023, 2024, 2025" in c["linea"]


def test_la_fecha_de_datos_sale_de_cargado_en_en_hora_de_costa_rica():
    tarde = (dt.datetime(2026, 11, 11, 3, 0, tzinfo=dt.timezone.utc), None)  # 21:00 del 10 en Costa Rica
    conn = piloto()
    conn.cur.c = tarde
    assert C.cobertura(conn)["datos_cargados_al"] == "2026-11-10"


def test_base_vacia_o_caida_levanta_nunca_cobertura_vacia():
    with pytest.raises(RuntimeError, match="no tiene documentos"):
        C.medir(Conn(vectores={}, por_anno={}, elegibles={}, cargado=CARGADO))
    with pytest.raises(ConnectionError):
        C.cobertura(piloto(error=ConnectionError("sin red")))


def test_memoria_de_diez_minutos_y_refresco_forzado():
    conn = piloto()
    reloj = iter([0.0, 5.0, 700.0])
    ahora = lambda: next(reloj)  # noqa: E731
    C.cobertura(conn, ahora)
    n1 = conn.cur.consultas
    C.cobertura(conn, ahora)  # a los 5 s: de la memoria
    assert conn.cur.consultas == n1
    C.cobertura(conn, ahora)  # a los 700 s: vuelve a medir
    assert conn.cur.consultas > n1


def test_caso_real_tribunales_sin_vectores_no_se_declaran_semanticos():
    """2026-11-19: la línea decía «búsqueda por significado en 2022, 2023, 2024, 2026 (Salas y tribunales)» y los tribunales de
    2022, 2024 y 2026 no tenían ni un vector ."""
    v = {("Sala Segunda de la Corte", 2023): 3409, ("Tribunal de Familia", 2023): 1352, ("Sala Segunda de la Corte", 2024): 3670}
    e = {(2023, "Sala Segunda de la Corte"): 3409, (2023, "Tribunal de Familia"): 1352,
         (2024, "Sala Segunda de la Corte"): 3670, (2024, "Tribunal de Familia"): 1192}
    linea = C.cobertura(piloto(vectores=v, elegibles=e))["linea"]
    assert "en las Salas en 2023, 2024; en los tribunales en 2023, y solo búsqueda literal en 2024" in linea, linea
    assert "Salas y tribunales" not in linea
