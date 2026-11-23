"""`verificar_cita`: veredicto sobre el texto de la base, con control positivo y negativo.

Textos armados con piezas reales de 2025 (ver `test_conector_fragmentos.py`): apéndice de voto salvado de la Sala Tercera,
voto salvado intercalado de la Sala Segunda, nota de la Sala Constitucional.
"""

import pytest
from test_conector_fragmentos import APENDICE, INTERCALADO, NOTA

from src.conector import verificar as V
from src.conector.ficha import DocumentoNoEncontrado

MAYORIA = "La prescripción empieza a correr desde que el derecho es exigible"
SALVADO = "no comparto lo resuelto por la mayoría de esta cámara"
EN_PT = "se declara inadmisible el recurso de casación interpuesto por el licenciado Omar Esteban Lau"


def test_control_positivo_frase_de_mayoria():
    # 1.3.0 fase A): lo que antes era `mayoria` es `considerando_sin_clasificar`, nunca criterio afirmado
    r = V.evaluar(APENDICE, MAYORIA)
    assert r["literal"] is True and r["seccion"] == "considerando_sin_clasificar"
    assert r["antes_de_dispositiva"] is True and not r["en_voto_salvado"] and not r["en_nota"]
    assert r["veredicto"].startswith("LITERAL_EN_CONSIDERANDO_SIN_CLASIFICAR")
    assert r["citable_como_criterio"] == "indeterminado" and r["estructura"] == "confiable"


def test_control_negativo_frase_inventada():
    r = V.evaluar(APENDICE, "el patrono transfirió la plenitud del xilófono jurisprudencial a la comunidad lunar")
    assert r["literal"] is False and r["seccion"] is None and r["ocurrencias"] == 0
    assert r["veredicto"].startswith("NO_LITERAL")


def test_frase_de_voto_salvado_se_marca_y_no_es_de_mayoria():
    r = V.evaluar(APENDICE, SALVADO)
    assert r["literal"] is True and r["seccion"] == "voto_salvado" and r["en_voto_salvado"] is True
    assert r["antes_de_dispositiva"] is False
    assert "no es criterio de la mayoría" in r["veredicto"]


def test_voto_salvado_intercalado_antes_de_la_dispositiva_tambien_se_marca():
    r = V.evaluar(INTERCALADO, "Nos apartamos de la decisión de la mayoría en el tanto consideramos")
    assert r["seccion"] == "voto_salvado" and r["en_voto_salvado"] is True
    assert r["antes_de_dispositiva"] is True  # está antes de la dispositiva y aun así NO es de mayoría: por eso hay `seccion`


def test_nota_separada():
    r = V.evaluar(NOTA, "El tema de los recursos de amparo relacionados con el derecho a la salud")
    assert r["seccion"] == "nota" and r["en_nota"] is True and r["veredicto"].startswith("LITERAL_SOLO_EN_NOTA")


def test_frase_de_la_dispositiva_y_del_resultando():
    assert V.evaluar(APENDICE, EN_PT)["seccion"] == "por_tanto"
    assert V.evaluar(NOTA, "alega una lista de espera para un ultrasonido")["seccion"] == "resultando"


def test_frase_en_mayoria_y_en_salvamento_vale_la_de_mayoria_y_avisa():
    texto = APENDICE + " " + MAYORIA + " dijo la disidente."
    r = V.evaluar(texto, MAYORIA)
    assert r["seccion"] == "considerando_sin_clasificar" and r["secciones"] == ["considerando_sin_clasificar", "voto_salvado"]
    assert "también aparece en: voto_salvado" in r["veredicto"]
    assert r["tambien_en_parte_no_criterio"] is False  # un voto salvado no es «parte no criterio» de la mayoría


def test_espacios_saltos_y_comillas_tipograficas_se_normalizan():
    texto = "Considerando: el tribunal dijo que “la caducidad\n   no opera de oficio”  en este caso concreto. POR TANTO: Se declara."
    assert V.evaluar(texto, 'que "la caducidad no opera de oficio" en este caso')["literal"] is True
    assert V.evaluar(texto, "que «la caducidad no opera de oficio» en este caso")["literal"] is True


def test_otra_caja_no_es_literal_pero_se_avisa():
    r = V.evaluar(APENDICE, MAYORIA.upper())
    assert r["literal"] is False and r["literal_ignorando_mayusculas"] is True and "mayúsculas" in r["veredicto"]


def test_frase_muy_corta_o_muy_larga_se_rechaza():
    with pytest.raises(ValueError, match="casi todo"):
        V.evaluar(APENDICE, "de la")
    with pytest.raises(ValueError, match="de a una cita"):
        V.evaluar(APENDICE, "palabra " * 400)


class Cur:
    def __init__(self, fila, error=None):
        self.fila, self.error, self.sql = fila, error, []

    def execute(self, sql, params=()):
        if self.error:
            raise self.error
        self.sql.append(sql)

    def fetchone(self):
        return self.fila


class Conn:
    def __init__(self, fila, error=None):
        self.c = Cur(fila, error)

    def cursor(self):
        return self.c


def test_verificar_cita_con_la_base_devuelve_enlace_y_nunca_texto_alrededor():
    conn = Conn((APENDICE, "Sala Tercera de la Corte"))
    r = V.verificar_cita(conn, "sen-1-0006-1317194", MAYORIA)
    assert r["id"] == "sen-1-0006-1317194" and r["enlace"].endswith("/document/sen-1-0006-1317194")
    assert r["seccion"] == "considerando_sin_clasificar"
    assert "despacho" in conn.c.sql[0]  # 1.3.0: lee el despacho, del que dependen los rótulos del fondo
    assert MAYORIA not in str(r)  # ni la frase ni lo que la rodea vuelven en la respuesta
    assert "se discute si el reclamo" not in str(r)


def test_id_inexistente_y_error_de_bd_no_son_un_no_literal():
    with pytest.raises(DocumentoNoEncontrado):
        V.verificar_cita(Conn(None), "sen-1-0034-9999999", MAYORIA)
    with pytest.raises(RuntimeError, match="BD caída"):
        V.verificar_cita(Conn(None, RuntimeError("BD caída")), "sen-1-0006-1317194", MAYORIA)


# --- 1.3.0: alegato, frase repetida, estructura no confiable y detector de `mayoria` -------------------------

from test_conector_ficha import PEGADA_14915  # noqa: E402
from test_conector_secciones_fondo import JUVENIL, MOTIVO_1303413, _textos, tercera  # noqa: E402

from src.conector import fragmentos as F  # noqa: E402
from src.conector import secciones_fondo as S  # noqa: E402
from src.indice.extracto import normalizar  # noqa: E402

FRASE_AGRAVIO = "la insuficiencia en la valoración de los indicios presentados"


@pytest.fixture
def encendido(monkeypatch):
    monkeypatch.setattr(S, "EMISION", S.EMISION_TOTAL)


def test_frase_de_alegato_no_es_criterio(encendido):
    r = V.evaluar(tercera(MOTIVO_1303413), FRASE_AGRAVIO, JUVENIL)
    assert r["seccion"] == "alegato" and r["veredicto"].startswith("LITERAL_EN_ALEGATO")
    assert r["citable_como_criterio"] == "no" and r["tambien_en_parte_no_criterio"] is False
    assert r["antes_de_dispositiva"] is True and r["estructura"] == "confiable"


def test_frase_de_alegato_repetida_despues_del_veredicto_avisa(encendido):
    repetida = MOTIVO_1303413 + " En efecto, la defensa alega " + FRASE_AGRAVIO + ", pero no demuestra el vicio."
    r = V.evaluar(tercera(repetida), FRASE_AGRAVIO, JUVENIL)
    assert r["seccion"] == "considerando_sin_clasificar" and r["secciones"] == ["considerando_sin_clasificar", "alegato"]
    assert r["tambien_en_parte_no_criterio"] is True and "puede ser la Sala repitiendo" in r["veredicto"]
    assert r["citable_como_criterio"] == "indeterminado"


def test_frase_de_veredicto(encendido):
    r = V.evaluar(tercera(MOTIVO_1303413), "El primer motivo de casación se declara inadmisible", JUVENIL)
    assert r["seccion"] == "veredicto" and "pasa o no pasa a estudio" in r["veredicto"] and r["citable_como_criterio"] == "indeterminado"


def test_estructura_no_confiable_no_ubica_las_partes():
    r = V.evaluar(PEGADA_14915, "Se anula la sentencia No. 22025010854", "Sala Constitucional")
    assert r["seccion"] == "estructura_no_confiable" and r["veredicto"].startswith("LITERAL_ESTRUCTURA_NO_CONFIABLE")
    # 1.4.0: la dispositiva se muestra (localizada), pero la frase no se ubica frente a ella: puede ser la de otra resolución
    assert r["antes_de_dispositiva"] is None and r["dispositiva_localizada"] is True and r["estructura"] == "no_confiable"
    assert r["citable_como_criterio"] == "indeterminado"


@pytest.mark.parametrize("emision", ["total", "vacia"])
def test_ningun_valor_mayoria_ni_literal_en_mayoria_ni_citable_si(monkeypatch, emision):
    """Se mira el VALOR de `seccion`/`secciones` y el código, no la palabra (los textos conservados dicen «de mayoría»)."""
    monkeypatch.setattr(S, "EMISION", S.EMISION_TOTAL if emision == "total" else {k: frozenset() for k in S.EMISION_TOTAL})
    textos = _textos() + [(APENDICE, "Sala Tercera de la Corte"), (INTERCALADO, "Sala Segunda de la Corte"),
                          (NOTA, "Sala Constitucional"), (PEGADA_14915, "Sala Constitucional")]
    vistos = set()
    for texto, despacho in textos:
        for via in ("literal", "semantica"):
            for terms in ((), ("motivo", "recurso")):
                for f in F.armar(texto, terms, via, despacho)["fragmentos"]:
                    assert f["seccion"] in F.SECCIONES and f["seccion"] != "mayoria"
        t = normalizar(texto)
        for p in range(0, len(t) - 60, 97):
            frase = " ".join(t[p:p + 60].split()[1:-1])
            if len(frase) < V.MIN_FRASE:
                continue
            r = V.evaluar(texto, frase, despacho)
            vistos.add(r["seccion"])
            assert r["seccion"] != "mayoria" and "mayoria" not in r["secciones"]
            assert "LITERAL_EN_MAYORIA" not in r["veredicto"] and r["citable_como_criterio"] != "si"
    assert len(vistos) >= 6  # control positivo: el recorrido sí pasó por muchas secciones distintas
    assert set(V.CITABLE) == set(F.SECCIONES) and "si" not in V.CITABLE.values()
