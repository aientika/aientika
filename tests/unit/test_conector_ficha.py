"""Ficha del conector: fecha, hora, número y redactor salen del propio fallo, con encabezados REALES.

Encabezados de fallos reales (2025): Sala Primera sen-1-0004-1337883, Sala Constitucional sen-1-0007-1304631, Sala Tercera
sen-1-0006-1276374 y Tribunal Agrario sen-1-0034-1336661. El «Redacta…» es de líneas reales de Sala Primera/Segunda.
"""

import datetime as dt

import pytest

from src.conector import ficha as Fi

PRIMERA = (" Exp: 14-000410-1178-LA Res. 001306-C-S1-2025 SALA PRIMERA DE LA CORTE SUPREMA DE JUSTICIA. San José, a las nueve "
           "horas treinta y tres minutos del veinticinco de setiembre de dos mil veinticinco .-\nEn proceso ordinario laboral de "
           "la COMPAÑÍA NACIONAL DE FUERZA Y LUZ contra la CAJA.\nRedacta la Magistrada Vargas Vásquez;\nCONSIDERANDO El presente "
           "asunto se origina en el reclamo.\nPOR TANTO: Se declara sin lugar el recurso. Notifíquese.")
CONSTITUCIONAL = ("Exp: 24-032712-0007-CO Res. Nº 2025011987 SALA CONSTITUCIONAL DE LA CORTE SUPREMA DE JUSTICIA. San José, a las "
                  "nueve horas veinte minutos del veinticinco de abril de dos mil veinticinco . Recurso de amparo. Resultando: 1.- "
                  "Por escrito presentado por fax a las 09:53 horas de 20 de noviembre de 2024.\nPor tanto:\nSe declara con lugar.")
TERCERA = ("\nExp: 24-000235-0006-PE Res: 2025-00033\nSALA DE CASACIÓN PENAL. San José, a las diez horas quince minutos del "
           "dieciséis de enero de dos mil veinticinco. Visto el procedimiento de revisión.\nConsiderando: I. Algo.\n"
           "Por Tanto: Se declara sin lugar la revisión. Notifíquese.")
AGRARIO = ("EXPEDIENTE: 25-000094-0507-AG - 2 PROCESO: ORDINARIO\nVOTO Nº N° 2025000863 TRIBUNAL AGRARIO.- A las diez horas "
           "cincuenta y seis minutos del cinco de setiembre de dos mil veinticinco.- PROCESO ORDINARIO establecido por X.\n"
           "POR TANTO: Se confirma. Redacta el magistrado Zamora Campos CONSIDERANDO")


@pytest.mark.parametrize("frase,esperado", [("cero", 0), ("nueve", 9), ("una", 1), ("veintitrés", 23), ("treinta y tres", 33),
                                            ("cincuenta y seis", 56), ("dos mil veinticinco", 2025), ("quince", 15),
                                            ("doce", 12), ("treinta y uno", 31)])
def test_numeros_en_letras(frase, esperado):
    assert Fi.numero_en_letras(frase) == esperado


def test_numero_en_letras_ilegible_es_none_no_cero():
    assert Fi.numero_en_letras("gato") is None and Fi.numero_en_letras("") is None


@pytest.mark.parametrize("texto,fecha,hora", [
    (PRIMERA, "2025-09-25", "09:33"), (CONSTITUCIONAL, "2025-04-25", "09:20"), (TERCERA, "2025-01-16", "10:15"),
    (AGRARIO, "2025-09-05", "10:56"),
    ("San José, a las nueve horas del primero de enero de dos mil veinticuatro.", "2024-01-01", "09:00")])
def test_encabezado_fecha_y_hora_del_fallo(texto, fecha, hora):
    assert Fi.encabezado(texto) == {"fecha": fecha, "hora": hora}


def test_encabezado_ausente_no_inventa():
    assert Fi.encabezado("Texto sin encabezado de fallo.") == {"fecha": None, "hora": None}


def test_hora_de_un_fax_dentro_del_fallo_no_se_toma_por_la_del_fallo():
    # «a las 09:53 horas de 20 de noviembre de 2024» es el fax del recurrente, no el encabezado (caso 12063-2026)
    assert Fi.encabezado(CONSTITUCIONAL)["hora"] == "09:20"


def test_redactor_solo_de_la_linea_redacta():
    assert Fi.redactor(PRIMERA) == "Vargas Vásquez"
    assert Fi.redactor(AGRARIO) == "Zamora Campos"  # se detiene antes de CONSIDERANDO
    assert Fi.redactor(TERCERA) is None  # control negativo: sin «Redacta» no se inventa


class Cur:
    def __init__(self, fila, error=None):
        self.fila, self.error = fila, error

    def execute(self, sql, params=()):
        if self.error:
            raise self.error

    def fetchone(self):
        return self.fila


class Conn:
    def __init__(self, fila, error=None):
        self.c = Cur(fila, error)

    def cursor(self):
        return self.c


def fila(texto, **kw):
    base = dict(id="sen-1-0004-1337883", despacho="Sala Primera de la Corte", tipo="SNT", numero="01306", padre=None,
                fecha=dt.date(2025, 9, 25), expediente="140004101178LA")
    base.update(kw)
    return (base["id"], base["despacho"], base["tipo"], base["numero"], base["padre"], base["fecha"], base["expediente"], texto)


def test_ficha_toma_los_datos_del_encabezado_y_no_del_metadato():
    f = Fi.ficha(Conn(fila(PRIMERA, fecha=dt.date(2025, 9, 24))), "sen-1-0004-1337883")
    assert (f["numero"], f["numero_origen"]) == ("001306-C-S1-2025", "encabezado del fallo")
    assert (f["fecha"], f["hora"], f["fecha_origen"]) == ("2025-09-25", "09:33", "encabezado del fallo")
    assert f["fecha_metadato_difiere"] is True  # el metadato decía el 24: se avisa, se usa el del fallo
    assert f["expediente"] == "14-000410-1178-LA"
    assert f["redactor"] == "Vargas Vásquez" and f["redactor_nota"] is None
    assert f["por_tanto"].startswith("POR TANTO: Se declara sin lugar")
    assert f["enlace"].endswith("/document/sen-1-0004-1337883")
    assert f["hay_disidencia"] is False and f["disidencias"] == []


def test_ficha_sin_redacta_omite_el_redactor_y_nunca_usa_el_metadato():
    f = Fi.ficha(Conn(fila(TERCERA, fecha=None)), "sen-1-0004-1337883")
    assert f["redactor"] is None and "metadato" in f["redactor_nota"]
    assert "Rivas" not in str(f)
    assert f["fecha"] == "2025-01-16" and f["fecha_metadato_difiere"] is False  # Tercera: el metadato venía vacío


def test_ficha_lista_las_disidencias():
    texto = TERCERA + "\nMagistrado suplente Voto salvado de la magistrada Vargas González\nNo comparto lo resuelto."
    f = Fi.ficha(Conn(fila(texto)), "sen-1-0004-1337883")
    assert f["hay_disidencia"] is True
    assert f["disidencias"][0]["tipo"] == "voto_salvado" and "Voto salvado" in f["disidencias"][0]["encabezado"]


def test_id_inexistente_levanta_y_error_de_bd_sube():
    with pytest.raises(Fi.DocumentoNoEncontrado):
        Fi.ficha(Conn(None), "sen-1-0034-9999999")
    with pytest.raises(RuntimeError, match="conexión perdida"):
        Fi.ficha(Conn(None, RuntimeError("conexión perdida")), "sen-1-0004-1337883")


# --- 1.3.0: guarda de estructura, tipo de resolución y disidencias----------------------

from src.conector import fragmentos as F  # noqa: E402
from src.conector import secciones_fondo as S  # noqa: E402
from src.indice.extracto import extraer, normalizar, por_tanto  # noqa: E402

FIRMAS_SC = ("Fernando Castillo V.\nPresidente Fernando Cruz C. Paul Rueda L. Luis Fdo. Salazar A. Jorge Araya G. Anamari Garro V. "
             "Ingrid Hess H. ")
# sen-1-0007-1304923 (14915-2025): sentencia que anula otra (dispositiva en 3745) y la anulada pegada después (18611).
PEGADA_14915 = (
    "Exp: 25-008630-0007-CO Res. N° 2025014915 SALA CONSTITUCIONAL DE LA CORTE SUPREMA DE JUSTICIA. San José, a las nueve horas "
    "del once de mayo de dos mil veinticinco. Gestión de nulidad.\nResultando:\n1.- La recurrente pide anular lo resuelto.\n"
    "Considerando:\nI.- Se advierte un error en la sentencia, artículo LXXXI. POR TANTO: Se anula la sentencia No. 22025010854 de "
    "las 10:05 horas de 8 de abril de 2025. Continúese con la tramitación del proceso. " + FIRMAS_SC + "Exp: 25-008630-0007-CO\n"
    "Res. N° 2025010854 SALA CONSTITUCIONAL DE LA CORTE SUPREMA DE JUSTICIA. San José, a las diez horas cinco minutos del ocho de "
    "abril de dos mil veinticinco . Recurso de amparo contra la CAJA COSTARRICENSE DE SEGURO SOCIAL.\nResultando:\n1.- Por escrito "
    "presentado en la Secretaría de la Sala el 26 de marzo de 2025, la persona recurrente interpuso recurso de amparo.\n"
    "Considerando:\nI.- OBJETO DEL RECURSO. La recurrente reclama la cirugía, artículo LXXXI.\nPor tanto:\nSe declara sin lugar el "
    "recurso. Notifíquese. " + FIRMAS_SC)
# sen-1-0007-1380421 (12839-2026): tres encabezados (24413, 32408, 60325).
TRES_12839 = (
    "Res. N° 2026012839 SALA CONSTITUCIONAL DE LA CORTE SUPREMA DE JUSTICIA. Habeas corpus.\nResultando:\n1.- Se recurre la "
    "prisión preventiva.\nConsiderando:\nI.- La medida debe prorrogarse por TRES MESES. POR TANTO Por las razones expuestas y "
    "artículos 39 y 41 constitucionales, se ordena la PRÓRROGA DE LA MEDIDA CAUTELAR. II.- Luego resolver lo que corresponda, de "
    "acuerdo al mérito de los autos.-\nPor tanto: Se anula la sentencia número 2009-014129 de las dieciséis horas diez minutos. "
    "III.- Consejo Superior, artículo LXXXI.\nPOR TANTO:\nSe declara con lugar el recurso sin ordenar la libertad del tutelado. "
    "Notifíquese. " + FIRMAS_SC)
# sen-1-0007-1290837 (13284-2025): resoluciones de extradición citadas con «(…) POR TANTO:» (89286 … 241186) y la propia (247387).
CITA_13284 = "lo estipulado en lo sucesivo es de obligatorio cumplimiento para Costa Rica (…) POR TANTO: De conformidad con lo estipulado se resuelve: A) Por extemporáneo se rechaza. "
SEIS_13284 = ("Res. N° 2025013284 SALA CONSTITUCIONAL DE LA CORTE SUPREMA DE JUSTICIA. Habeas corpus.\nResultando:\n1.- Extradición.\n"
              "Considerando:\nI.- Antecedentes del proceso. " + CITA_13284 * 5 + "II.- Consejo Superior nro. 43-12 de 3 de mayo de "
              "2012. Por tanto: Se declara sin lugar el recurso. " + FIRMAS_SC)


# 1.4.0 (opción b): la guarda ya no deja `por_tanto` en null; muestra la que elige `extracto.por_tanto`, SIEMPRE con aviso.
# 14915-2025 es el control: la mostrada es la de la sentencia anulada pegada después (equivocada), y por eso el aviso no se quita.
@pytest.mark.parametrize("texto,n,empieza", [(PEGADA_14915, 2, "Por tanto: Se declara sin lugar"),
                                             (TRES_12839, 3, "POR TANTO: Se declara con lugar"),
                                             (SEIS_13284, 6, "Por tanto: Se declara sin lugar")])
def test_guarda_muestra_la_dispositiva_elegida_con_aviso_que_dice_lo_medido(texto, n, empieza):
    f = Fi.ficha(Conn(fila(texto, despacho="Sala Constitucional")), "sen-1-0007-1304923")
    assert f["estructura"] == "no_confiable" and f["dispositiva_localizada"] is True
    assert f["por_tanto"] == recortar_hoy(por_tanto(normalizar(texto))[1]) and f["por_tanto"].startswith(empieza)
    assert f"el conector encontró {n} encabezados de dispositiva" in f["por_tanto_aviso"]
    assert "puede ser el de otra resolución" in f["por_tanto_aviso"] and "verificalo en el fallo" in f["por_tanto_aviso"]
    assert F.MEDIDA_GUARDA in f["por_tanto_aviso"] and "PENDIENTE" not in f["por_tanto_aviso"]
    assert f["tipo_resolucion"] == "sin_determinar"
    a = F.armar(texto, ["recurso"], "literal", "Sala Constitucional")
    assert a["por_tanto"] and a["dispositiva_localizada"] is True and a["por_tanto_aviso"] == f["por_tanto_aviso"]
    assert all(x["seccion"] == "estructura_no_confiable" for x in a["fragmentos"])


def test_guarda_por_otra_resolucion_a_continuacion_con_un_solo_encabezado():
    solo_una = PEGADA_14915.replace("\nPor tanto:\nSe declara sin lugar el recurso.", " Se resolverá luego.")
    assert len(S.guarda(normalizar(solo_una))) == 3 and S.guarda(normalizar(solo_una))[:2] == ("no_confiable", 1)
    f = Fi.ficha(Conn(fila(solo_una, despacho="Sala Constitucional")), "x")
    assert f["por_tanto"].startswith("POR TANTO: Se anula") and "otra resolución a continuación de la dispositiva" in f["por_tanto_aviso"]
    assert "puede no ser la de este voto" in f["por_tanto_aviso"]
    sin_pegar = solo_una[:solo_una.find("Exp: 25-008630-0007-CO\nRes.")]  # control negativo: sin la resolución pegada
    assert S.guarda(normalizar(sin_pegar)) == ("confiable", 1, None)


# sen-1-1258-1283039 (126-2025): cinco «por tanto» que NO son encabezado (20304, 24782, 25093, 47509) y la dispositiva (41024).
CONECTORES_1283039 = (
    "\nExp: 24-000235-0006-PE Res: 2025-00126\nSALA DE CASACIÓN PENAL. San José, a las diez horas.\nConsiderando: I. El recurso "
    "es una inconformidad con el contenido del por tanto que fue dictado por el tribunal sentenciador. II. En el Código Procesal "
    "Penal no se requiere para el dictado del \"por tanto\" una explicación profusa. Por tanto, es palmario para esta Sala que lo "
    "que existe es un desacuerdo. Así las cosas, se declara inadmisible el presente motivo. La magistrada Vargas González salva el "
    "voto.\nPor Tanto: Por mayoría, se declaran inadmisibles los dos motivos presentados en el recurso de casación incoado por el "
    "licenciado Iván Alexander Quirós Wanters. La magistrada Vargas González salva el voto. Notifíquese. Patricia Solano C. "
    "VOTO SALVADO DE LA MAGISTRADA VARGAS GONZÁLEZ Por las razones que expondré, el recurso de casación es extraordinario y, por "
    "tanto, está sometido a una serie de rigores formalistas.")


def test_guarda_confiable_con_por_tanto_como_conector_y_dispositiva_identica_a_la_de_hoy():
    t = normalizar(CONECTORES_1283039)
    assert S.guarda(t) == ("confiable", 1, None)
    f = Fi.ficha(Conn(fila(CONECTORES_1283039, despacho="Sala Tercera Materia Penal Juvenil")), "sen-1-1258-1283039")
    assert f["por_tanto"] == recortar_hoy(por_tanto(t)[1]) and f["por_tanto"].startswith("Por Tanto: Por mayoría")
    assert f["dispositiva_localizada"] is True and f["por_tanto_aviso"] is None and f["tipo_resolucion"] == "admisibilidad"
    a = F.armar(CONECTORES_1283039, [], "literal", "Sala Tercera Materia Penal Juvenil")
    assert a["por_tanto"] == F.recortar(F.sin_cola_de_firmas(extraer(t).por_tanto), F.MAX_POR_TANTO)  # como en la 1.2.0


def recortar_hoy(disp):
    return F.recortar(disp, Fi.MAX_POR_TANTO_FICHA)


@pytest.mark.parametrize("disp,esperado", [
    ("Por tanto: Se declaran inadmisibles los recursos de casación interpuestos por [Nombre 003].", "admisibilidad"),  # 1313540
    ("Por tanto: Se admiten los dos motivos del recurso de casación formulado por la licenciada Ericka Chaves.", "admisibilidad"),  # 1298610
    ("Por tanto: Se declara admisible el recurso de casación formulado por el defensor público.", "admisibilidad"),  # 1349395
    ("Por tanto: Por cumplir con los requisitos legales, se admite para su trámite, el presente procedimiento.", "admisibilidad"),  # 1283864
    ("Por Tanto: Se declaran sin lugar las impugnaciones incoadas por la representación del Ministerio Público.", "sin_determinar"),  # 1371375
    ("POR TANTO: Se acoge el recurso, se declara con lugar y se admite la prueba.", "sin_determinar"),
    (None, "sin_determinar"), ("", "sin_determinar"),
])
def test_tipo_resolucion_por_lexema(disp, esperado):
    assert S.tipo_resolucion(disp) == esperado


def test_tipo_resolucion_en_la_ficha_sale_de_la_dispositiva_del_fallo():
    assert Fi.ficha(Conn(fila(TERCERA.replace("sin lugar la revisión", "inadmisible la revisión"))), "x")["tipo_resolucion"] == "admisibilidad"
    assert Fi.ficha(Conn(fila(TERCERA)), "x")["tipo_resolucion"] == "sin_determinar"  # «sin lugar»: no es admisibilidad


def test_ficha_lista_un_voto_parcialmente_salvado_que_la_1_2_0_no_veia():
    # sen-1-0006-1285000 78718: «Voto parcialmente salvado de la magistrada…» tras las firmas
    texto = TERCERA + (" Gerardo Rubén Alfaro V. Sandra Eugenia Zúñiga M. Magistrado suplente Voto parcialmente salvado de la "
                       "magistrada Vargas González\nAunque coincido en lo restante, no comparto la decisión.")
    f = Fi.ficha(Conn(fila(texto)), "sen-1-0006-1285000")
    assert f["hay_disidencia"] is True and f["disidencias"][0]["encabezado"].startswith("Voto parcialmente salvado")
