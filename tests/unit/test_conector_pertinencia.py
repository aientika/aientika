"""Pertinencia de los resultados: distancia expuesta, grupo
comparado, `grupo_chico` y su aviso. Estos tests cubren la aritmética de Python y el armado de la respuesta con la base falsa de
`test_conector_buscar`; NO prueban el SQL real. Constantes importadas.
"""

import pytest
from test_conector_buscar import COB, VEC, Conn, fila

from src.conector import buscar as B
from src.conector import pertinencia as PT

CONSULTA = "prescripción laboral caducidad"


@pytest.fixture(autouse=True)
def cobertura_fija(monkeypatch):
    monkeypatch.setattr(B, "cobertura", lambda conn: COB)


# --- funciones puras ------------------------------------------------------------------------------------------------------

def test_estado_en_sus_bordes():
    assert PT.estado(False, 10_000) == PT.SIN_VECTOR_DE_CONSULTA
    assert PT.estado(True, 0) == PT.FILTRO_SIN_VECTORES
    assert PT.estado(True, PT.N_MINIMO - 1) == PT.GRUPO_CHICO
    assert PT.estado(True, PT.N_MINIMO) == PT.SIN_EVALUAR  # el borde ya no es chico


def test_distancia_ausente_es_none_nunca_cero():
    assert PT.distancia(None) is None
    assert PT.distancia(0.4567) == round(0.4567, PT.DECIMALES)


def test_aviso_solo_para_grupo_chico_con_resultados_por_significado():
    assert PT.aviso(PT.GRUPO_CHICO, 15, True, 0).startswith("El filtro tiene solo 15 fallos")
    assert PT.aviso(PT.GRUPO_CHICO, 15, False, 0) is None  # sin resultados por significado no hay de qué avisar
    assert PT.aviso(PT.SIN_EVALUAR, 5000, True, 0) is None
    assert "Por palabras, 2 de los fallos" in PT.aviso(PT.GRUPO_CHICO, 15, True, 2)


# --- respuesta de buscar --------------------------------------------------------------------------------------------------

def _conn(comparados, sem=(("s1", 0.412), ("s2", 0.5)), literal=()):
    ids = [i for i, _ in sem] + [i for i, *_ in literal]
    return Conn(sem=list(sem), literal=list(literal), textos={i: fila(i) for i in ids}, comparados=comparados)


def test_semanticos_traen_distancia_y_literales_no():
    conn = _conn(5000, literal=[("l1", True, 0), ("x1", False, 0)])
    r = B.buscar(conn, CONSULTA, vector_consulta=VEC)
    por_id = {x["id"]: x for x in r["resultados"]}
    assert por_id["s1"]["distancia"] == PT.distancia(0.412) and por_id["s2"]["distancia"] == PT.distancia(0.5)
    assert "distancia" not in por_id["l1"]  # control negativo: un literal no trae distancia (ausencia ≠ cero)
    assert all("distancia" not in x for x in r["solo_literal"])
    assert r["distancia_corte"] == PT.distancia(0.5)  # la del último candidato semántico
    assert r["senal_semantica"] == {"estado": PT.SIN_EVALUAR, "comparados": 5000}


def test_grupo_chico_avisa_y_el_borde_no():
    chico = B.buscar(_conn(PT.N_MINIMO - 1), CONSULTA, vector_consulta=VEC)
    assert chico["senal_semantica"]["estado"] == PT.GRUPO_CHICO
    assert f"solo {PT.N_MINIMO - 1} fallos" in chico["aviso"]
    borde = B.buscar(_conn(PT.N_MINIMO), CONSULTA, vector_consulta=VEC)
    assert borde["senal_semantica"]["estado"] == PT.SIN_EVALUAR and borde["aviso"] is None


def test_sin_vector_no_cuenta_ni_trae_distancias():
    conn = Conn(literal=[("l1", True, 0)], textos={"l1": fila("l1")})
    r = B.buscar(conn, CONSULTA)
    assert r["senal_semantica"] == {"estado": PT.SIN_VECTOR_DE_CONSULTA, "comparados": 0}
    assert r["distancia_corte"] is None and "distancia" not in r["resultados"][0]
    assert not any("count(*) FROM vectores v" in s for s in conn.cur.sql)


def test_filtro_sin_vectores():
    r = B.buscar(_conn(0, sem=()), CONSULTA, vector_consulta=VEC)
    assert r["senal_semantica"]["estado"] == PT.FILTRO_SIN_VECTORES and r["distancia_corte"] is None


def test_el_vector_va_primero_en_los_parametros_de_la_consulta_semantica():
    conn = _conn(5000)
    B.buscar(conn, CONSULTA, vector_consulta=VEC)
    k = next(n for n, s in enumerate(conn.cur.sql) if "AS dist FROM vectores v" in s)
    assert conn.cur.params[k][0].startswith("[") and conn.cur.params[k][1] == B.MODELO
    assert "ORDER BY dist, d.id_documento" in conn.cur.sql[k]  # desempate estable


def test_aviso_de_grupo_chico_reconoce_el_acierto_literal_en_vez_de_contradecirlo():
    literal = [("s1", True, 0), ("l1", True, 0), ("l2", True, 0)]  # >= MINIMO_LITERAL: se queda en el nivel estricto
    r = B.buscar(_conn(15, literal=literal), CONSULTA, vector_consulta=VEC)
    assert r["literal"]["nivel"] == len(B.terminos(CONSULTA))
    assert "Por palabras, 3 de los fallos" in r["aviso"]  # s1 (ambas), l1 y l2 contienen todos los términos
    sin_literal = B.buscar(_conn(15), CONSULTA, vector_consulta=VEC)
    assert "Por palabras" not in sin_literal["aviso"]  # control negativo


def test_orden_de_avisos_truncado_antes_que_pertinencia():
    literal = [("l1", True, B.CANDIDATOS_FRASE + 1)]
    r = B.buscar(_conn(15, literal=literal), '"relación laboral"', vector_consulta=VEC)
    assert r["aviso"].index(str(B.CANDIDATOS_FRASE)) < r["aviso"].index("El filtro tiene solo")
