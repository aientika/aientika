"""El «por tanto» recortado no queda a media oración y se marca.

Caso de referencia: la 2026030881 (sen-1-0007-1420825). Con el corte por palabra a 400 caracteres, la dispositiva terminaba en
«La magistrada Garro Vargas salva parcialmente el voto y ordena la condenatoria…», y Claude le atribuyó la condena en costas que
el fallo le niega («pero no en costas»).
"""

from src.conector import fragmentos as F
from src.conector.instrucciones import INSTRUCCIONES

DISPOSITIVA_30881 = (
    "POR TANTO:\nSe declara con lugar el recurso, con base en lo dispuesto por el artículo 52, párrafo 1º, de la Ley de la "
    "Jurisdicción Constitucional, sin especial condenatoria en costas, daños y perjuicios. El Magistrado Salazar Alvarado salva "
    "parcialmente el voto y dispone la condenatoria en daños, perjuicios y costas. La magistrada Garro Vargas salva parcialmente "
    "el voto y ordena la condenatoria en daños y perjuicios, pero no en costas. Notifíquese.-")


def test_la_dispositiva_de_la_30881_no_se_corta_a_media_oracion_y_se_marca():
    assert len(DISPOSITIVA_30881) > F.MAX_POR_TANTO  # precondición: el caso real se recorta
    pt, recortado = F.recortar_dispositiva(DISPOSITIVA_30881, F.MAX_POR_TANTO)
    assert recortado is True and len(pt) <= F.MAX_POR_TANTO
    assert pt.endswith("daños, perjuicios y costas. […]")
    assert "Garro Vargas" not in pt  # ni media oración de la magistrada: o entera o nada
    # control negativo: el corte viejo por palabra sí dejaba la oración de Garro a medias
    assert F.recortar(DISPOSITIVA_30881, F.MAX_POR_TANTO).endswith("ordena la condenatoria…")


def test_dispositiva_corta_no_se_marca():
    pt, recortado = F.recortar_dispositiva("POR TANTO: Se declara sin lugar el recurso. Notifíquese.", F.MAX_POR_TANTO)
    assert recortado is False and pt == "POR TANTO: Se declara sin lugar el recurso. Notifíquese."


def test_sin_oracion_que_entre_entera_se_corta_por_palabra():
    larga = "POR TANTO: " + "se ordena " * 80 + "lo que corresponda."
    pt, recortado = F.recortar_dispositiva(larga, F.MAX_POR_TANTO)
    assert recortado is True and pt.endswith("…") and len(pt) <= F.MAX_POR_TANTO


def test_armar_expone_el_campo_y_las_instrucciones_lo_explican():
    texto = "Res. N° 2026030881 SALA CONSTITUCIONAL.\nResultando:\n1.- Recurso.\nConsiderando:\nI.- Fondo del asunto. " + DISPOSITIVA_30881
    a = F.armar(texto, ["recurso"], "literal", "Sala Constitucional")
    assert a["por_tanto_recortado"] is True and "Garro" not in a["por_tanto"]
    assert "`por_tanto_recortado`" in INSTRUCCIONES and "pedí la `aientika_ficha_de_fallo`" in INSTRUCCIONES
