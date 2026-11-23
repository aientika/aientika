"""`buscar` y `voyage_consulta` del conector: reglas de la consulta, secciones, tope, y errores que nunca son «cero resultados».

La base se simula con un cursor que contesta por tipo de SQL; las filas tienen la forma de las reales de la base de jurisprudencia
(id `sen-1-NNNN-NNNNNNN`, despacho, tipo SNT, número, fecha, expediente, texto). Controles positivos y negativos.
"""

import datetime as dt

import pytest
from test_conector_fragmentos import APENDICE, SIN_DISIDENCIA

from src.conector import buscar as B
from src.conector import voyage_consulta as VC
from src.indice.embeber_voyage import ErrorVoyage
from src.indice.tope_voyage import SinOptOut

PARES = ["Sala Primera de la Corte|2025", "Sala Constitucional|2025"]
COB = {"linea": "COBERTURA: prueba.", "pares_con_vectores": PARES}


def fila(i, texto=SIN_DISIDENCIA, despacho="Sala Primera de la Corte"):
    return (i, despacho, "SNT", "01306", dt.date(2025, 9, 25), "140004101178LA", texto)


class Cur:
    """Contesta según el SQL: semántica, literal o lectura de textos. Guarda lo ejecutado."""

    def __init__(self, sem=(), literal=(), textos=None, error_en=None, comparados=None):
        # `sem`: ids (distancias crecientes desde 0.30) o pares (id, distancia), como devuelve la consulta real.
        self.sem = [x if isinstance(x, tuple) else (x, round(0.30 + k / 100, 2)) for k, x in enumerate(sem)]
        self.lit, self.textos, self.error_en = list(literal), textos or {}, error_en
        self.comparados = len(self.sem) * 100 if comparados is None else comparados  # grupo grande por defecto
        self.sql, self.params, self.rows = [], [], []

    def execute(self, sql, params=()):
        self.sql.append(sql)
        self.params.append(params)
        if self.error_en and self.error_en in sql:
            raise ConnectionError("conexión perdida con la base")
        if "SELECT count(*) FROM vectores v" in sql:
            self.rows = [(self.comparados,)]
        elif "FROM vectores v" in sql:
            self.rows = list(self.sem)
        elif "WITH q AS" in sql:
            self.rows = list(self.lit) or [(None, None, 0)]
        elif "FROM documentos WHERE id_documento = ANY" in sql:
            self.rows = [self.textos[i] for i in params[0] if i in self.textos]
        else:
            self.rows = []

    def fetchall(self):
        return self.rows


class Conn:
    def __init__(self, **kw):
        self.cur, self.rollbacks = Cur(**kw), 0

    def cursor(self):
        return self.cur

    def rollback(self):
        self.rollbacks += 1


@pytest.fixture(autouse=True)
def cobertura_fija(monkeypatch):
    monkeypatch.setattr(B, "cobertura", lambda conn: COB)


VEC = [0.1] * B.DIMENSION


def test_terminos_sin_vacias_sin_repetir_y_con_guiones_intactos():
    assert B.terminos("¿Desde cuándo empieza a correr la prescripción de los derechos laborales?") == [
        "empieza", "correr", "prescripción", "derechos", "laborales"]  # «cuándo» es vacía
    assert B.terminos("y la 10-12-13 de la Gerencia Financiera, gerencia") == ["10-12-13", "gerencia", "financiera"]
    assert B.terminos("de la en el") == []  # control negativo: solo vacías


def test_consulta_natural_baja_de_nivel_con_los_terminos_mas_largos():
    niveles = B._consultas_literales("Indicios de una relación laboral encubierta bajo un contrato de servicios profesionales")
    assert [len(n[1]) for n in niveles] == [7, 5, 3, 2]
    assert all(n[2] == [] and n[3] is False for n in niveles)
    assert set(niveles[-1][1]) == {"encubierta", "profesionales"}  # lo más específico queda al final


def test_comillas_son_una_frase_confirmada_sobre_el_texto_no_un_websearch():
    (texto, terms, frases, operadores), = B._consultas_literales('"relación laboral" encubierta')
    assert frases == ["relación laboral"] and operadores is False
    assert texto == "relación laboral encubierta" and terms == ["relación", "laboral", "encubierta"]


def test_operadores_or_y_menos_van_a_websearch():
    assert B._consultas_literales("prescripcion or caducidad")[0][3] is True
    assert B._consultas_literales("prescripcion -caducidad")[0][3] is True


def test_consulta_sin_terminos_utiles_se_rechaza():
    with pytest.raises(ValueError, match="términos útiles"):
        B._consultas_literales("de la en el")


def test_patron_de_frase_escapa_y_acepta_cualquier_comilla():
    p = B._patron_frase('d) Que "se" ordene 10-12-13.')
    assert p.startswith("d\\)[[:space:]]+Que[[:space:]]+") and p.endswith("10-12-13\\.")
    assert p.count("[\"'«»“”]") == 2


def test_filtros_a_sql_y_parametros():
    sql, p = B._filtros("Sala Primera", 2025, "2025-01-01", "2025-06-30")
    assert sql.count("%s") == 4 and p == ["Sala Primera", 2025, "2025-01-01", "2025-06-30"]
    assert "coalesce(d.fecha, make_date(d.anno, d.mes, 1))" in sql  # Sala Tercera trae la fecha vacía
    assert B._filtros(None, None, None, None) == ("", [])
    assert B._filtros("100%_x", None, None, None)[1] == ["100\\%\\_x"]  # el LIKE no se deja inyectar comodines


def test_rrf_premia_lo_que_aparece_en_las_dos_listas():
    assert B._rrf(["a", "b", "c"], ["c", "b"])[:2] == [("c", 2), ("b", 2)]
    assert B._rrf([], []) == []


def test_buscar_separa_con_vectores_de_solo_literal_y_abre_con_la_cobertura():
    textos = {i: fila(i) for i in ("s1", "s2", "l1", "x1", "x2")}
    conn = Conn(sem=["s1", "s2"], literal=[("l1", True, 0), ("s2", True, 0), ("x1", False, 0), ("x2", False, 0)], textos=textos)
    r = B.buscar(conn, "prescripción laboral caducidad", vector_consulta=VEC)
    assert r["cobertura"] == "COBERTURA: prueba." and r["semantica_usada"] is True
    assert [x["id"] for x in r["resultados"]] == ["s2", "s1", "l1"]
    assert {x["id"]: x["via"] for x in r["resultados"]} == {"s2": "ambas", "s1": "semantica", "l1": "literal"}
    assert [x["id"] for x in r["solo_literal"]] == ["x1", "x2"]
    assert all(x["via"] == "literal" for x in r["solo_literal"]) and r["total"] == 5


def test_buscar_nunca_pasa_de_diez_y_guarda_lugar_para_solo_literal():
    ids = [f"s{i}" for i in range(30)]
    sin = [f"x{i}" for i in range(30)]
    textos = {i: fila(i) for i in ids + sin}
    conn = Conn(sem=ids, literal=[(i, True, 0) for i in ids] + [(i, False, 0) for i in sin], textos=textos)
    r = B.buscar(conn, "prescripción laboral caducidad", vector_consulta=VEC)
    assert len(r["resultados"]) == 6 and len(r["solo_literal"]) == 4 and r["total"] == B.MAX_RESULTADOS
    sin_solo = Conn(sem=ids, literal=[(i, True, 0) for i in ids], textos=textos)
    assert len(B.buscar(sin_solo, "prescripción laboral caducidad", vector_consulta=VEC)["resultados"]) == 10


def test_cada_resultado_trae_lo_prometido_y_el_enlace_oficial():
    conn = Conn(sem=["s1"], literal=[], textos={"s1": fila("sen-1-0004-1337883", APENDICE)})
    conn.cur.textos = {"s1": fila("s1", APENDICE)}
    x = B.buscar(conn, "prescripción casación", vector_consulta=VEC)["resultados"][0]
    # 1.3.0 fase A): `dispositiva_localizada`, `por_tanto_aviso` y `tipo_resolucion` se agregan a lo prometido
    assert set(x) == {"id", "numero", "fecha", "despacho", "tipo", "expediente", "via", "distancia", "fragmentos", "por_tanto",
                      "por_tanto_recortado",  # 1.5.0: el «por tanto» recortado se marca
                      "dispositiva_localizada", "por_tanto_aviso", "tipo_resolucion", "hay_disidencia", "enlace"}
    assert x["dispositiva_localizada"] is True and x["por_tanto_aviso"] is None
    assert all(f["seccion"] != "mayoria" and f["abre_con_veredicto"] is False for f in x["fragmentos"])
    assert x["enlace"] == "https://nexuspj.poder-judicial.go.cr/document/s1" and x["hay_disidencia"] is True
    assert x["fecha"] == "2025-07-24"  # la del encabezado del fallo, no la del metadato (2025-09-25)
    assert len(x["fragmentos"]) <= 2
    assert all(len(f["texto"]) <= 600 and f["seccion"] for f in x["fragmentos"])


def test_sin_vector_solo_corre_la_literal_y_lo_dice():
    conn = Conn(literal=[("l1", True, 0)], textos={"l1": fila("l1")})
    r = B.buscar(conn, "prescripción laboral caducidad")
    assert r["semantica_usada"] is False and not any("FROM vectores v" in s for s in conn.cur.sql)
    assert r["resultados"][0]["via"] == "literal"


def test_sql_natural_usa_plainto_y_solo_la_frase_agrega_la_confirmacion_sobre_el_texto():
    conn = Conn(literal=[("l1", True, 0)], textos={"l1": fila("l1")})
    B.buscar(conn, "prescripción laboral caducidad")
    lit = next(s for s in conn.cur.sql if "WITH q AS" in s)
    assert "plainto_tsquery" in lit and "websearch" not in lit and "~*" not in lit
    conn2 = Conn(literal=[("l1", True, 0)], textos={"l1": fila("l1")})
    B.buscar(conn2, '"prescripción laboral" caducidad')
    assert "~*" in next(s for s in conn2.cur.sql if "WITH q AS" in s)
    conn3 = Conn(literal=[("l1", True, 0)], textos={"l1": fila("l1")})
    B.buscar(conn3, "prescripcion or caducidad")
    assert "websearch_to_tsquery" in next(s for s in conn3.cur.sql if "WITH q AS" in s)


def test_aflojar_el_and_se_detiene_cuando_hay_suficientes():
    conn = Conn(literal=[("l1", True, 0)] * 1, textos={"l1": fila("l1")})
    B.buscar(conn, "indicios relación laboral encubierta contrato servicios profesionales")
    assert sum("WITH q AS" in s for s in conn.cur.sql) == len(B._NIVELES)  # 1 resultado < mínimo: llegó al último nivel
    conn2 = Conn(literal=[(f"l{i}", True, 0) for i in range(5)], textos={f"l{i}": fila(f"l{i}") for i in range(5)})
    B.buscar(conn2, "indicios relación laboral encubierta contrato servicios profesionales")
    assert sum("WITH q AS" in s for s in conn2.cur.sql) == 1


def test_error_de_bd_sube_y_cierra_la_transaccion_no_es_cero_resultados():
    conn = Conn(error_en="WITH q AS")
    with pytest.raises(ConnectionError, match="conexión perdida"):
        B.buscar(conn, "prescripción laboral caducidad")
    assert conn.rollbacks == 1
    conn2 = Conn(sem=["s1"], error_en="FROM vectores v")
    with pytest.raises(ConnectionError):
        B.buscar(conn2, "prescripción laboral", vector_consulta=VEC)


def test_id_que_la_busqueda_devolvio_y_la_base_no_tiene_es_error():
    with pytest.raises(RuntimeError, match="ids que la búsqueda devolvió"):
        B.buscar(Conn(literal=[("fantasma", True, 0)], textos={}), "prescripción laboral caducidad")


def test_vacio_real_avisa_que_no_prueba_inexistencia():
    r = B.buscar(Conn(), "prescripción laboral caducidad")
    assert r["total"] == 0 and "No prueba que no exista jurisprudencia" in r["aviso"]


def test_preseleccion_de_frase_truncada_se_declara():
    conn = Conn(literal=[("l1", True, B.CANDIDATOS_FRASE + 1)], textos={"l1": fila("l1")})
    r = B.buscar(conn, '"relación laboral"')
    assert r["literal"]["candidatos_truncados"] is True and str(B.CANDIDATOS_FRASE) in r["aviso"]


def test_entradas_invalidas():
    with pytest.raises(ValueError, match="consulta vacía"):
        B.buscar(Conn(), "   ")
    with pytest.raises(ValueError, match="dimensiones"):
        B.buscar(Conn(), "prescripción laboral", vector_consulta=[0.1] * 10)


def test_se_fija_un_tiempo_maximo_por_consulta():
    conn = Conn(literal=[("l1", True, 0)], textos={"l1": fila("l1")})
    B.buscar(conn, "prescripción laboral caducidad")
    assert conn.cur.sql[0] == f"SET LOCAL statement_timeout = '{B.TIEMPO_MAXIMO}'"


# ---- voyage_consulta -------------------------------------------------------------------------------------------------

class Cliente:
    def __init__(self, vectores=None):
        self.llamadas, self.vectores = [], vectores

    def embeber(self, textos, modelo, tipo="document"):
        self.llamadas.append((textos, modelo, tipo))
        return (self.vectores if self.vectores is not None else [[0.0] * 1024]), 12


@pytest.fixture
def con_opt_out(monkeypatch):
    monkeypatch.setenv("VOYAGE_OPT_OUT_CONFIRMADO", "2026-11-07")


def test_sin_opt_out_no_se_reserva_ni_se_llama(monkeypatch):
    monkeypatch.delenv("VOYAGE_OPT_OUT_CONFIRMADO", raising=False)
    cli, reservas = Cliente(), []
    with pytest.raises(SinOptOut):
        VC.embeber_consulta("prescripción laboral", reservas.append, cli)
    assert reservas == [] and cli.llamadas == []


def test_sin_reservar_inyectado_no_se_gasta(con_opt_out):
    cli = Cliente()
    with pytest.raises(VC.PresupuestoNoInyectado):
        VC.embeber_consulta("prescripción laboral", cliente=cli)
    assert cli.llamadas == []


def test_reserva_antes_de_llamar_y_pide_modelo_y_tipo_query(con_opt_out):
    cli, reservas = Cliente(), []
    v = VC.embeber_consulta("  prescripción   laboral ", reservas.append, cli)
    assert len(v) == 1024 and reservas and reservas[0] >= 8
    assert cli.llamadas == [(["prescripción laboral"], "voyage-4", "query")]


def test_presupuesto_agotado_corta_antes_de_llamar(con_opt_out):
    def reservar(tokens):
        raise RuntimeError("tope de consultas alcanzado")
    cli = Cliente()
    with pytest.raises(RuntimeError, match="tope"):
        VC.embeber_consulta("prescripción laboral", reservar, cli)
    assert cli.llamadas == []


def test_respuesta_de_voyage_con_forma_equivocada_es_error(con_opt_out):
    with pytest.raises(ErrorVoyage, match="dimensiones"):
        VC.embeber_consulta("prescripción laboral", lambda t: None, Cliente(vectores=[[0.0] * 10]))
    with pytest.raises(ValueError, match="vacía"):
        VC.embeber_consulta("   ", lambda t: None, Cliente())
    with pytest.raises(ValueError, match="máximo"):
        VC.embeber_consulta("x " * 2000, lambda t: None, Cliente())


def test_voyage_ocupado_no_se_reintenta_con_esperas():
    with pytest.raises(ErrorVoyage, match="no se reintenta"):
        VC._no_esperar(5)
