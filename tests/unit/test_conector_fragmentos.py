"""Fragmentos, secciones y enlace del conector, con control positivo y negativo.

Los textos arman, con relleno de cuerpo, piezas REALES recortadas de fallos de 2025: el encabezado y el
apéndice de voto salvado de la Sala Tercera (sen-1-0006-1317194), el voto salvado intercalado antes del POR TANTO de la Sala
Segunda (sen-1-0034-1335524) y la nota intercalada de la Sala Constitucional (sen-1-0007-1296950).
"""

import re

from src.conector import fragmentos as F
from src.indice.extracto import normalizar

CUERPO = ("Considerando: I. Se discute si el reclamo del actor estaba prescrito cuando se presentó la demanda. "
          "La prescripción empieza a correr desde que el derecho es exigible, y así lo ha entendido esta Sala de manera reiterada. "
          "II. En el caso concreto, el accionante cesó su relación el 3 de marzo y reclamó hasta casi dos años después, "
          "de modo que el plazo ordinario ya había transcurrido. " * 6)

# Sala Tercera: dispositiva firmada y, después, el voto salvado como apéndice.
APENDICE = (
    "\nExp: 19-000981-0276-PE Res: 2025-00804\nSALA DE CASACIÓN PENAL. San José, a las once horas doce minutos del veinticuatro "
    "de julio del dos mil veinticinco. Visto el recurso de casación interpuesto en causa seguida contra [Nombre 003], por el "
    "delito de abuso sexual agravado contra persona menor de edad, en perjuicio de [Nombre 002]., y;\n" + CUERPO +
    "\nPor Tanto: Por mayoría, se declara inadmisible el recurso de casación interpuesto por el licenciado Omar Esteban Lau "
    "Núñez, defensor particular del imputado. La magistrada Vargas González salva el voto. Notifíquese. Gerardo Rubén Alfaro V. "
    "Sandra Eugenia Zúñiga M. Patricia Vargas G.\nMagistrado suplente Magistrado suplente Voto salvado de la magistrada Vargas "
    "González\nPor las razones que de seguido expondré, no comparto lo resuelto por la mayoría de esta cámara en cuanto a la "
    "inadmisibilidad decretada. La conceptualización del recurso de casación como garantía exige admitirlo y el plazo "
    "razonable de la causa lo confirma.")

# Sala Segunda: el voto salvado va ANTES del POR TANTO de mayoría.
INTERCALADO = (
    "SALA SEGUNDA DE LA CORTE SUPREMA DE JUSTICIA. San José, a las diez horas cuarenta minutos del veintinueve de agosto de dos "
    "mil veinticinco. Proceso ordinario establecido ante el Juzgado de Trabajo del Primer Circuito Judicial de San José.\n"
    + CUERPO + "En lo demás, el fallo debe permanecer incólume.\nX.- VOTO SALVADO DE LOS MAGISTRADOS OLASO ÁLVAREZ Y CAMPOS "
    "ESQUIVEL: Nos apartamos de la decisión de la mayoría en el tanto consideramos que el accionante tiene derecho a la "
    "revalorización de su salario conforme a la fórmula prevista en la resolución DG-078-89.\nPOR TANTO: Se acoge "
    "parcialmente el recurso de la parte actora y se deniega el del demandado. En consecuencia, se anula la sentencia recurrida "
    "en cuanto denegó el ajuste en vacaciones. Notifíquese.")

NOTA = (
    "Exp: 24-035814-0007-CO Res. N° 2025000456 SALA CONSTITUCIONAL DE LA CORTE SUPREMA DE JUSTICIA. San José, a las nueve horas "
    "veinte minutos del ocho de enero de dos mil veinticinco . Recurso de amparo interpuesto contra la CAJA COSTARRICENSE DE "
    "SEGURO SOCIAL (CCSS). Resultando: 1.- Por medio del escrito agregado al expediente la recurrente alega una lista de "
    "espera para un ultrasonido. 2.- Informa la autoridad recurrida que ya se programó la cita.\n" + CUERPO +
    "\nVIII.- Nota del magistrado Rueda Leal. El tema de los recursos de amparo relacionados con el derecho a la salud y, sobre "
    "todo, el de las listas de espera son agravios que se han tornado recurrentes en esta Sala.\nPor tanto:\nSe declara con "
    "lugar el recurso, con base en lo dispuesto por el artículo 52 de la Ley de la Jurisdicción Constitucional. El magistrado "
    "Rueda Leal consigna nota. Notifíquese.")

SIN_DISIDENCIA = ("Resolución 2025-1 SALA PRIMERA. Resultando: 1.- La actora reclama el pago de aguinaldo. " + CUERPO +
                  "\nPOR TANTO: Se declara sin lugar el recurso. Notifíquese.")


def _pos(texto, frase):
    i = normalizar(texto).find(frase)
    assert i >= 0, frase
    return i


def test_enlace_oficial():
    assert F.enlace("sen-1-0004-1337883") == "https://nexuspj.poder-judicial.go.cr/document/sen-1-0004-1337883"


def test_secciones_apendice_de_la_sala_tercera():
    t = normalizar(APENDICE)
    m = F.mapa_secciones(t)
    assert F.seccion_en(m, _pos(APENDICE, "La prescripción empieza a correr")) == "considerando_sin_clasificar"  # 1.3.0: era `mayoria`
    assert F.seccion_en(m, _pos(APENDICE, "Por mayoría, se declara inadmisible")) == "por_tanto"
    assert F.seccion_en(m, _pos(APENDICE, "no comparto lo resuelto")) == "voto_salvado"
    assert F.hay_disidencia(t, m)


def test_secciones_voto_salvado_intercalado_termina_en_la_dispositiva():
    t = normalizar(INTERCALADO)
    m = F.mapa_secciones(t)
    assert F.seccion_en(m, _pos(INTERCALADO, "Nos apartamos de la decisión")) == "voto_salvado"
    assert F.seccion_en(m, _pos(INTERCALADO, "se anula la sentencia recurrida")) == "por_tanto"
    assert F.seccion_en(m, _pos(INTERCALADO, "La prescripción empieza")) == "considerando_sin_clasificar"  # 1.3.0: era `mayoria`


def test_nota_y_resultando_se_rotulan():
    t = normalizar(NOTA)
    m = F.mapa_secciones(t)
    assert F.seccion_en(m, _pos(NOTA, "El tema de los recursos de amparo")) == "nota"
    assert F.seccion_en(m, _pos(NOTA, "alega una lista de espera")) == "resultando"
    assert F.seccion_en(m, _pos(NOTA, "La prescripción empieza")) == "considerando_sin_clasificar"  # 1.3.0: era `mayoria`


def test_control_negativo_fallo_sin_disidencia():
    t = normalizar(SIN_DISIDENCIA)
    m = F.mapa_secciones(t)
    assert m.marcas == [] and not F.hay_disidencia(t, m)


def test_armar_ventana_de_mayoria_con_el_termino_y_sin_salirse_a_la_disidencia():
    r = F.armar(APENDICE, ["prescripción", "casación"])
    assert 1 <= len(r["fragmentos"]) <= 2
    for f in r["fragmentos"]:
        assert len(f["texto"]) <= F.MAX_FRAGMENTO
        assert f["seccion"] in F.SECCIONES
        assert "no comparto" not in f["texto"]  # control: nada del voto salvado en un fragmento de mayoría
    assert r["fragmentos"][0]["seccion"] == "considerando_sin_clasificar"  # 1.3.0: era `mayoria`
    assert "prescripción" in r["fragmentos"][0]["texto"]
    assert r["hay_disidencia"] is True


def test_armar_termino_ausente_cae_al_objeto_y_al_fondo():
    r = F.armar(NOTA, ["xilofono"])
    assert r["fragmentos"], "sin coincidencias debe haber objeto o fondo, no cero fragmentos"
    assert r["fragmentos"][0]["seccion"] == "resultando"
    assert "xilofono" not in r["fragmentos"][0]["texto"]


def test_termino_sin_tilde_encuentra_la_palabra_con_tilde():
    r = F.armar(SIN_DISIDENCIA, ["prescripcion"])
    assert any("prescripción" in f["texto"] for f in r["fragmentos"])


def test_por_tanto_de_mayoria_recortado_y_sin_disidencia_pegada():
    r = F.armar(INTERCALADO, [])
    assert r["por_tanto"].startswith("POR TANTO: Se acoge parcialmente")
    assert len(r["por_tanto"]) <= F.MAX_POR_TANTO
    assert "Nos apartamos" not in r["por_tanto"]
    largo = F.armar(SIN_DISIDENCIA.replace("sin lugar el recurso.", "sin lugar el recurso " + "y se ordena algo más " * 60 + "."), [])
    assert len(largo["por_tanto"]) <= F.MAX_POR_TANTO and largo["por_tanto"].endswith("…")


def test_cola_de_firmas_huerfana_se_quita():
    sucio = "Por tanto: Se rechaza de plano el recurso. El magistrado Rueda Leal da"  # caso real de la Sala Constitucional
    assert F.sin_cola_de_firmas(sucio) == "Por tanto: Se rechaza de plano el recurso."
    assert F.sin_cola_de_firmas("Por tanto: Se declara con lugar el recurso") == "Por tanto: Se declara con lugar el recurso"


def test_recortar_corta_en_palabra_y_marca():
    assert F.recortar("uno  dos\ntres", 50) == "uno dos tres"
    corto = F.recortar("palabra " * 100, 40)
    assert len(corto) <= 40 and corto.endswith("…") and " " not in corto[-3:-1]


def test_la_ventana_no_cruza_el_borde_de_la_dispositiva():
    t = normalizar(APENDICE)
    m = F.mapa_secciones(t)
    ini = t.find("Por Tanto:") - 80
    w = F._ventana(t, ini, F._limite(m, ini, len(t)))
    assert "Por Tanto" not in w and w.endswith("…")
    assert re.fullmatch(r"…?.*", w, re.S)


# --- 1.3.0: votos salvados por forma, fuera de la zona, fragmento con veredicto -----

import pytest  # noqa: E402
from test_conector_secciones_fondo import JUVENIL, MOTIVO_1303413, tercera  # noqa: E402

from src.conector import secciones_fondo as S  # noqa: E402
from src.conector import verificar as V  # noqa: E402

PT_PENAL = ("\nPor Tanto: Por mayoría, se declara inadmisible el segundo reparo incoado. La magistrada Vargas González salva el voto "
            "parcialmente. Notifíquese. Jesús Alberto Ramírez Q. Gerardo Rubén Alfaro V. Patricia Vargas G. Magistrado suplente ")
# Encabezados que la 1.2.0 no marcaba, con el arranque real del voto (id y posición del encabezado).
DESPUES_DE_LAS_FIRMAS = [
    ("Voto parcialmente salvado de la magistrada Vargas González\nAunque coincido en lo restante, no comparto la decisión de "
     "declarar inadmisibles algunos motivos de los recursos formulados", "no comparto la decisión de declarar inadmisibles"),  # 1285000 78718
    ("Voto parcialmente salvado de la magistrada Vargas González\nAunque coincido en admitir el segundo motivo del recurso "
     "formulado por el ente fiscal, no comparto la inadmisibilidad decretada", "no comparto la inadmisibilidad decretada"),  # 1283878 35814
    ("VOTO PARCIALMENTE SALVADO DE LA MAGISTRADA VARGAS GONZÁLEZ Aunque coincido en lo restante, no comparto la decisión de "
     "declarar inadmisible el tercer motivo", "declarar inadmisible el tercer motivo"),  # 1333889 17191
    ("Voto Salvado de la magistrada Vargas González Por las razones que de seguido expondré, no comparto lo resuelto por la "
     "mayoría de esta cámara en cuanto declara inadmisibles los dos motivos", "en cuanto declara inadmisibles los dos motivos"),  # 1337825 30162
    ("VOTO PARCIALMENTE SALVADO DE LA MAGISTRADA SOLANO CASTRO Y EL MAGISTRADO ALFARO VARGAS En lo que respecta al motivo "
     "tercero del recurso de casación planteado", "En lo que respecta al motivo tercero"),  # 1432720 54023
    ("Magistrado suplente dcastrillom (828-3/7-3-24)\nLa magistrada Corrales Pampillo salva el voto Con sumo respeto me separo de "
     "la decisión de mayoría por las razones que procedo a exponer.", "Con sumo respeto me separo"),  # 1316407 36598
]
# Sala Primera: el voto salvado va ANTES del POR TANTO, con numeral (1409698 23068) o a media línea (1351429 23965).
VOTO_PRIMERA = ("Voto salvado de las magistradas Rojas Morales y Vargas Vásquez. Se respeta pero no se comparte el criterio de "
                "mayoría por los siguientes motivos: Deviene injustificable la aplicación de requerimientos formalistas.")
PRIMERA_ANTES = [
    ("SALA PRIMERA DE LA CORTE SUPREMA DE JUSTICIA. CONSIDERANDO I. El recurso no cumple. II. Las carencias argumentativas de "
     "los agravios en su relación con el fallo recurrido. X. " + VOTO_PRIMERA + "\nPOR TANTO: Se rechaza de plano el recurso."),
    ("SALA PRIMERA DE LA CORTE SUPREMA DE JUSTICIA. CONSIDERANDO El recurso no cumple: carencias argumentativas del agravio en "
     "su relación con el fallo recurrido. " + VOTO_PRIMERA + "\nPOR TANTO: Se rechaza de plano el recurso."),
]


@pytest.fixture
def sin_formas_nuevas(monkeypatch):
    """Apaga las marcas por forma: el comportamiento sin ellas, para comparar."""
    monkeypatch.setattr(F, "marcas_por_forma", lambda texto, i_pt: [])


@pytest.mark.parametrize("voto,frase", DESPUES_DE_LAS_FIRMAS)
def test_formas_de_voto_salvado_tras_las_firmas(voto, frase):
    r = V.evaluar(tercera(MOTIVO_1303413, dispositiva=PT_PENAL + voto), frase, JUVENIL)
    assert r["seccion"] == "voto_salvado" and r["veredicto"].startswith("LITERAL_SOLO_EN_VOTO_SALVADO")
    assert r["citable_como_criterio"] == "no"


@pytest.mark.parametrize("voto,frase", DESPUES_DE_LAS_FIRMAS)
def test_sin_la_regla_de_3_5_el_voto_queda_posterior_a_dispositiva_nunca_sin_clasificar(sin_formas_nuevas, voto, frase):
    r = V.evaluar(tercera(MOTIVO_1303413, dispositiva=PT_PENAL + voto), frase, JUVENIL)
    assert r["seccion"] == "posterior_a_dispositiva" and r["veredicto"].startswith("LITERAL_DESPUES_DE_DISPOSITIVA")


@pytest.mark.parametrize("texto", PRIMERA_ANTES)
def test_voto_salvado_de_la_primera_antes_del_por_tanto(texto):
    r = V.evaluar(texto, "Deviene injustificable la aplicación", "Sala Primera de la Corte")
    assert r["seccion"] == "voto_salvado" and r["antes_de_dispositiva"] is True


@pytest.mark.parametrize("texto", PRIMERA_ANTES)
def test_control_sin_la_regla_el_voto_de_la_primera_saldria_sin_clasificar(sin_formas_nuevas, texto):
    assert V.evaluar(texto, "Deviene injustificable la aplicación", "Sala Primera de la Corte")["seccion"] == "considerando_sin_clasificar"


@pytest.mark.parametrize("mencion", [
    "Por mayoría (con el voto salvado de la magistrada Vargas González) se declara inadmisible el cuarto motivo de casación.",  # 1371379 40642
    "Por mayoría (con el voto salvado de las magistradas Vargas González y Ulloa Ramírez) se declara inadmisible la queja.",  # 1432720 17616
])
def test_mencion_en_minuscula_no_es_marca(mencion):
    t = normalizar(tercera(MOTIVO_1303413 + " " + mencion))
    assert F.marcas_por_forma(t, -1) == [] and F.mapa_secciones(t, JUVENIL).marcas == []


@pytest.mark.parametrize("cola", [
    "[Nombre 003].. La magistrada Vargas González salva el voto. Notifíquese. Patricia Solano C.",  # 1283039 41268
    "de la endilgada [Nombre 001]. La magistrada Vargas González salva el voto. Notifíquese. Patricia Solano C.",  # 1330587 14002
    "bajo el patrocinio de su abogado particular. La magistrada Vargas González salva el voto. Notifíquese. Gerardo Rubén Alfaro V.",  # 1371377 26493
])
def test_el_anuncio_de_la_dispositiva_no_es_marca(cola):
    t = normalizar(tercera(MOTIVO_1303413, dispositiva="\nPor Tanto: Por mayoría, se declara inadmisible el recurso " + cola))
    m = F.mapa_secciones(t, JUVENIL)
    assert F.marcas_por_forma(t, m.i_pt) == []
    anuncio = t.find("salva el voto. Notifíquese")
    sin_punto = t[:anuncio] + "salva el voto Con sumo respeto me separo." + t[anuncio + len("salva el voto. Notifíquese."):]
    assert F.marcas_por_forma(sin_punto, m.i_pt)  # control positivo: sin el punto, sí es encabezado (1316407)


def test_razones_de_los_magistrados_no_es_nota():
    # sen-1-0006-1352638 9360: «El reclamo es inadmisible. Razones de los magistrados Segura, Alfaro, Corrales y Herrera.»
    t = tercera("Solicita se revoque la sentencia. El reclamo es inadmisible. Razones de los magistrados Segura, Alfaro, Corrales "
                "y Herrera. (A) Algunas precisiones conceptuales previas.")
    assert V.evaluar(t, "Algunas precisiones conceptuales previas", "Sala Tercera de la Corte")["seccion"] != "nota"


def test_fuera_de_la_zona_encabezado_y_posterior(sin_formas_nuevas):
    t = tercera(MOTIVO_1303413, dispositiva=PT_PENAL + DESPUES_DE_LAS_FIRMAS[0][0])
    r = V.evaluar(t, "Visto el recurso de casación interpuesto en la presente causa", JUVENIL)
    assert r["seccion"] == "encabezado_del_fallo" and r["veredicto"].startswith("LITERAL_EN_ENCABEZADO")
    assert r["citable_como_criterio"] == "indeterminado"
    assert V.evaluar(t, "Jesús Alberto Ramírez Q. Gerardo Rubén Alfaro", JUVENIL)["seccion"] == "posterior_a_dispositiva"


def test_via_semantica_abre_con_el_primer_veredicto_y_cruza_su_borde(monkeypatch):
    monkeypatch.setattr(S, "EMISION", S.EMISION_TOTAL)
    t = tercera(MOTIVO_1303413)
    r = F.armar(t, ["fotografía"], "semantica", JUVENIL)
    primero = r["fragmentos"][0]
    assert primero["abre_con_veredicto"] is True and primero["seccion"] == "considerando_sin_clasificar"
    assert primero["texto"].startswith("…El primer motivo de casación se declara inadmisible. Previo a establecer")
    assert len(r["fragmentos"]) == 2 and r["fragmentos"][1]["abre_con_veredicto"] is False
    assert r["tipo_resolucion"] == "admisibilidad"
    lit = F.armar(t, ["fotografía"], "literal", JUVENIL)  # la vía literal sigue igual: no abre con el veredicto
    assert not any(f["abre_con_veredicto"] for f in lit["fragmentos"])
    monkeypatch.setattr(S, "EMISION", {k: frozenset() for k in S.EMISION_TOTAL})  # sin veredicto emitido: como hoy
    assert not any(f["abre_con_veredicto"] for f in F.armar(t, ["fotografía"], "semantica", JUVENIL)["fragmentos"])


def test_ventana_literal_no_sale_de_voto_salvado_ni_de_lo_posterior():
    t = tercera(MOTIVO_1303413, dispositiva=PT_PENAL + DESPUES_DE_LAS_FIRMAS[0][0])
    r = F.armar(t, ["inadmisibles", "comparto"], "literal", JUVENIL)
    assert r["fragmentos"] and all("no comparto" not in f["texto"] for f in r["fragmentos"])
    assert all(f["seccion"] not in ("voto_salvado", "nota", "posterior_a_dispositiva") for f in r["fragmentos"])
