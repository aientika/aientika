"""Catálogo de Aiéntika con la fecha más actualizada de cada fuente y, en jurisprudencia, las salas,
los tribunales y las fechas de las sentencias. Las filas imitan una medición real de la base (51 despachos)."""

import datetime as dt
import json

import pytest

from src.conector import catalogo_fuentes as K, cobertura as C
from src.conector.instrucciones import INSTRUCCIONES

D = dt.date
FILAS_REALES = [  # (despacho, resoluciones, primer año, último año, primera, más reciente) como las devuelve la base
    ("Tribunal Contencioso Administrativo", 26655, 2022, 2026, D(2022, 1, 4), D(2026, 9, 30)),
    ("Sala Primera de la Corte", 18531, 2022, 2026, D(2022, 1, 6), D(2026, 10, 29)),
    ("Sala Constitucional", 189140, 2022, 2026, D(2022, 1, 3), D(2026, 11, 4)),
    ("Tribunal Contencioso Administrativo Sección IX", 33, 2022, 2023, D(2022, 1, 11), D(2023, 2, 15)),
]


class Cur:
    def __init__(self, filas, error=None):
        self.filas, self.error, self.consultas = filas, error, 0

    def execute(self, sql, params=()):
        if self.error:
            raise self.error
        self.consultas += 1
        assert "GROUP BY 1" in sql and "fecha <= current_date" in sql  # una fecha futura no es «la más reciente»
        assert "extract(year FROM fecha) = anno" in sql  # 2026-11-13: «1990-01-05» en un voto de 2023 decía «desde 1990»

    def fetchall(self):
        return self.filas


class Conn:
    def __init__(self, filas, error=None):
        self.cur = Cur(filas, error)

    def cursor(self):
        return self.cur


@pytest.fixture(autouse=True)
def sin_memoria():
    C._cache.clear()
    yield
    C._cache.clear()


COB = {"annos_cargados": list(range(2022, 2027)), "documentos_por_anno": {2025: 300000, 2026: 64000},
       "datos_cargados_al": "2026-11-13", "fallos_hasta": "2026-11-04"}
TRAMITES = {"tramites": 2194, "instituciones": 140, "actualizado": "2026-11-13"}


def test_despachos_salas_primero_con_primera_y_mas_reciente():
    d = C.despachos(Conn(FILAS_REALES))
    assert [x["despacho"] for x in d] == ["Sala Constitucional", "Sala Primera de la Corte", "Tribunal Contencioso Administrativo",
                                          "Tribunal Contencioso Administrativo Sección IX"]
    assert d[0] == {"despacho": "Sala Constitucional", "resoluciones": 189140, "annos": "2022-2026", "desde": "2022-01-03",
                    "hasta": "2026-11-04"}


def test_despachos_base_vacia_o_caida_falla_nunca_lista_vacia():
    with pytest.raises(RuntimeError, match="no tiene documentos"):
        C.despachos(Conn([]))
    with pytest.raises(ConnectionError):
        C.despachos(Conn(FILAS_REALES, ConnectionError("sin red")))


def test_despachos_memoria_de_diez_minutos():
    conn, reloj = Conn(FILAS_REALES), iter([0.0, 5.0, 700.0])
    ahora = lambda: next(reloj)  # noqa: E731
    C.despachos(conn, ahora)
    C.despachos(conn, ahora)
    assert conn.cur.consultas == 1
    C.despachos(conn, ahora)
    assert conn.cur.consultas == 2


def test_catalogo_trae_fecha_de_cada_fuente_y_tabla_por_sala_y_tribunal():
    s = K.armar(COB, TRAMITES, C.despachos(Conn(FILAS_REALES)))
    nombres = [f["fuente"] for f in s["fuentes"]]
    assert "Jurisprudencia de las Salas y tribunales" in nombres and "Catálogo Nacional de Trámites" in nombres
    juri = next(f for f in s["fuentes"] if f["fuente"].startswith("Jurisprudencia"))
    assert juri["actualizado_al"] == "2026-11-13" and juri["periodo"] == "2022-2026" and "2026-11-04" in juri["mas_reciente"]
    assert juri["cantidad"] == "364.000 resoluciones"
    assert "| 2.194 trámites de 140 instituciones | vigentes en el catálogo | 2026-11-13 |" in s["tabla"]
    assert "| Sala Constitucional | 189.140 | 2022-2026 | 2022-01-03 | 2026-11-04 |" in s["tabla_jurisprudencia"]
    assert "| Tribunal Contencioso Administrativo Sección IX | 33 | 2022-2023 | 2022-01-11 | 2023-02-15 |" in s["tabla_jurisprudencia"]
    assert [f["fuente"] for f in s["en_incorporacion"]] == ["Votos del Tribunal Registral Administrativo"]
    assert "no está al día en la base" in s["como_mostrarlo"]


def test_lo_que_no_se_pudo_leer_dice_no_disponible_nunca_cero():
    s = K.armar(None, None, None)
    assert all(f["actualizado_al"] == K.NO_DISPONIBLE and f["cantidad"] == K.NO_DISPONIBLE for f in s["fuentes"])
    assert s["jurisprudencia_por_despacho"] == K.NO_DISPONIBLE and "tabla_jurisprudencia" not in s
    assert "| 0 " not in s["tabla"]


def test_el_catalogo_no_nombra_el_sistema_de_consulta():
    # La fuente de la jurisprudencia es la base de Aiéntika; el modelo no debe nombrar otro sistema de consulta como fuente.
    s = K.armar(COB, TRAMITES, C.despachos(Conn(FILAS_REALES)))
    assert "nexus" not in json.dumps(s, ensure_ascii=False).lower()


def test_las_instrucciones_mandan_al_catalogo_ante_preguntas_de_fuentes_y_fechas():
    assert "qué Salas o tribunales cubre o hasta qué fecha está actualizada, usá `aientika_catalogo_de_fuentes`" in INSTRUCCIONES
