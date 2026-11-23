"""`secciones_fondo` y su cortador con control positivo y negativo en cada regla.

Los textos son EXTRACTOS de fallos reales, con el id y la posición de origen al lado. Donde la regla necesita la estructura
(cortador, alegato), el texto mínimo conserva las marcas que importan: numerales, encabezados de motivo, veredicto, conectores.
"""

import pytest

from src.conector import fragmentos as F
from src.conector import secciones_fondo as S
from src.conector.secciones_cortador import candidatos
from src.indice.extracto import normalizar

ROM = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"]
TERCERA, JUVENIL, HACIENDA = "Sala Tercera de la Corte", "Sala Tercera Materia Penal Juvenil", "Sala Tercera Penal de Hacienda y Función Pública"
PRIMERA, SEGUNDA, CONSTITUCIONAL = "Sala Primera de la Corte", "Sala Segunda de la Corte", "Sala Constitucional"

# sen-1-1258-1303413, pos. 0-1100: encabezado, «Considerando:» y considerando I.
ENC_TERCERA = ("Exp: 24-000082-0071-PE Res: 2025-00571\nSALA DE CASACIÓN PENAL. San José, a las once horas veintidós minutos del "
               "treinta de mayo de dos mil veinticinco. Visto el recurso de casación interpuesto en la presente causa seguida contra "
               "[Nombre 001], por el delito de homicidio calificado, cometido en perjuicio de [Nombre 002]; y,\nConsiderando: I. El "
               "licenciado David Fernández Tercero, defensor particular del joven infractor [Nombre 001], formuló recurso de "
               "casación ( folios 185 a 195), contra la resolución N° 2025-041 BIS, dictada a las 13:36 horas del 05 de marzo de "
               "2025, por el Tribunal de Apelación de Sentencia Penal Juvenil del Segundo Circuito Judicial de San José. ")
# sen-1-1258-1330587 14002 / sen-1-1258-1283039 41024: dispositiva y firmas de la Tercera.
PT_TERCERA = ("\nPor Tanto: Por mayoría, se declara inadmisible el recurso de casación formulado por la defensora pública. "
              "Notifíquese. Patricia Solano C. Sandra Eugenia Zúñiga M. Patricia Vargas G. Giovanni Mena A. Magistrado suplente ")

# sen-1-1258-1303413 II (pos. 955-4300): encabezado de motivo, agravio, petitorio, veredicto que sigue al petitorio (3997).
AGRAVIO = "Argumenta que reclamó en los motivos primero y segundo del recurso de apelación de sentencia la insuficiencia en la valoración de los indicios presentados."
MOTIVO_1303413 = (
    'Primer motivo: reclama "errónea aplicación de un precepto legal procesal: artículo 142 del Código Procesal Penal. Referente '
    'a la fundamentación de la sentencia" (folio 185 vuelto). ' + AGRAVIO + " Refiere que la sentencia recurrida se orientó a "
    "sustentar el fallo de juicio más que a analizar los yerros alegados, limitándose por tanto en cuestionar la forma en que la "
    "defensa estructuró sus argumentos. Señala que dicho fallo no explica por qué el relato de un testigo directo y presencial, "
    "rendido bajo juramento, carece de valor. Solicita se declare con lugar el motivo, se revoque la sentencia número 2025-041 "
    "BIS que impugna. El primer motivo de casación se declara inadmisible. Previo a establecer las razones por las que no es de "
    "recibo el reparo incoado, se proceden a realizar algunas precisiones sobre el recurso.")


def tercera(*considerandos, dispositiva=PT_TERCERA):
    """Fallo mínimo de la Tercera: encabezado real, considerando I real y los considerandos dados desde el II."""
    return ENC_TERCERA + " ".join(f"{ROM[k]}. {c}" for k, c in enumerate(considerandos, 1)) + dispositiva


def mapa(texto, despacho=JUVENIL):
    return F.mapa_secciones(normalizar(texto), despacho)


def seccion(texto, frase, despacho=JUVENIL):
    t = normalizar(texto)
    assert frase in t, frase
    return F.seccion_en(F.mapa_secciones(t, despacho), t.find(frase))


@pytest.fixture
def encendido(monkeypatch):
    """Todos los rótulos encendidos: las reglas se prueban como las verá el usuario final."""
    monkeypatch.setattr(S, "EMISION", S.EMISION_TOTAL)


# --- emisión y familias -------------------------------------------------------------------------------------------------

def test_emision_es_la_decision_medida_sobre_la_reserva():
    #: solo `antecedente`, solo en Constitucional y Segunda
    assert S.EMISION == {"Constitucional": frozenset({"antecedente"}), "Primera": frozenset(),
                         "Segunda": frozenset({"antecedente"}), "Tercera": frozenset()}
    assert seccion(tercera(MOTIVO_1303413), AGRAVIO) == "considerando_sin_clasificar"  # `alegato` falló: no se emite


def test_con_la_emision_medida_la_segunda_da_antecedente_pero_no_alegato():
    t = SEGUNDA_1431950  # sin el fixture `encendido`: es lo que recibe el colega
    assert seccion(t, "ANTECEDENTES: En la demanda", SEGUNDA) == "antecedente"
    assert seccion(t, "Acusa la errónea valoración", SEGUNDA) == "considerando_sin_clasificar"


def test_con_la_familia_encendida_el_mismo_texto_si_da_alegato(encendido):
    assert seccion(tercera(MOTIVO_1303413), AGRAVIO) == "alegato"  # control positivo del anterior


def test_familia_apagada_por_la_constante_cae_a_sin_clasificar(monkeypatch):
    monkeypatch.setattr(S, "EMISION", {**S.EMISION_TOTAL, "Tercera": frozenset({"antecedente"})})
    t = tercera(MOTIVO_1303413)
    assert seccion(t, AGRAVIO) == "considerando_sin_clasificar"
    assert seccion(t, "El primer motivo de casación se declara") == "considerando_sin_clasificar"
    assert mapa(t).clasif.primer_veredicto is None


@pytest.mark.parametrize("despacho", ["Tribunal de Apelación de Sentencia Penal", "Juzgado Penal de Hacienda", None])
def test_fuera_de_las_seis_salas_no_hay_antecedente_alegato_ni_veredicto(encendido, despacho):
    m = mapa(tercera(MOTIVO_1303413), despacho)
    assert m.clasif.tramos == () and m.clasif.primer_veredicto is None
    assert seccion(tercera(MOTIVO_1303413), AGRAVIO, despacho) == "considerando_sin_clasificar"


# --- cortador ---------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("texto", [
    'sí mismo." (Clariá Olmedo, Jorge E. Derecho Procesal Penal. Tomo II. El Proceso Penal. Buenos Aires: Rubinzal',  # 1283039 9914
    ". Paul Rueda L. Luis Fdo. Salazar A. Jorge Araya G. Anamari Garro V. Ingrid Hess H. Exp: 25-008630",  # 1304923 3986
    "del tribunal de apelación de sentencia penal, específicamente en el considerando XXIII. La defensora pública determina",  # 1333572
    "las de la experiencia común…\" (CAFFERATA NORES, José I. Temas de Derecho Procesal Penal. Ediciones Depalma",  # 1432720 27525
    "medidas tomadas por la U.E. respecto a la X.F. y que como medida se requería una certificación",  # 1401477 37247
])
def test_no_son_numerales_de_considerando(texto):
    assert candidatos(texto, 0, len(texto), 0) == []


def test_numerales_reales_tras_punto_y_tras_salto_de_linea():
    real = "Considerando: I. El licenciado David Fernández. II. Primer motivo: reclama."  # 1303413
    assert [n for _, _, n in candidatos(real, 0, len(real), len("Considerando:"))] == [1, 2]
    titulo = "presentó escrito de adhesión al recurso de nulidad. Recurso de nulidad de Mabinsa\nII.- Examinados los fundamentos"
    assert [n for _, _, n in candidatos(titulo, 0, len(titulo), 0)] == [2]  # 1293163 6560: título en renglón propio


# sen-1-0034-1431950 (pos. 1700-12500), Sala Segunda: «II.- AGRAVIOS:» con agravios internos I a VI y luego el «III.-» real.
SEGUNDA_1431950 = (
    "SALA SEGUNDA DE LA CORTE SUPREMA DE JUSTICIA. San José, a las quince horas nueve minutos del veinticinco de setiembre de "
    "dos mil veintiséis. Proceso ordinario laboral establecido ante el JUZGADO CIVIL, TRABAJO Y AGRARIO DE TURRIALBA. Redacta la "
    "Magistrada Chacón Artavia; y, CONSIDERANDO: I.- ANTECEDENTES: En la demanda, el actor solicitó que en sentencia se declare "
    "\"que la totalidad de los auxilios y subsidios por enfermedad tienen carácter de salario. Por tanto, el Estado debe cesar de "
    "inmediato la práctica ilegal\" (sic). Inconforme con lo resuelto, el accionante plantea recurso de casación. "
    "II.- AGRAVIOS: I. – La parte recurrente solicita la nulidad de la sentencia. Sostiene que la sentencia incurre en una "
    "incongruencia grave. II. – Reprocha la infracción a las reglas de la carga dinámica de la prueba (artículo 478 del Código de "
    "Trabajo). III. – Acusa la errónea valoración probatoria y omisión de prueba relevante. IV. – Advierte error de hecho y de "
    "derecho en el análisis de la obligación con respecto al salario escolar. V. – Reprocha la inaplicación del artículo 174 "
    "inciso c) del Estatuto de Servicio Civil. VI. – Objeta la inobservancia de jurisprudencia reciente y la condena en costas "
    "impuesta en primera instancia. III.- NULIDAD DE LA SENTENCIA: En el presente caso se observa un vicio procesal que causa "
    "indefensión a la parte actora, por lo que resulta innecesario analizar los demás reparos formulados por la recurrente. "
    "IV.- CONSIDERACIONES FINALES: Con sustento en las razones expuestas, procede acoger el recurso del actor.\n"
    "POR TANTO: Se anula la sentencia número doscientos treinta y tres. Notifíquese.")


def test_agravios_de_la_segunda_con_secuencia_interna_resultado_fijado(encendido):
    t = SEGUNDA_1431950
    assert seccion(t, "ANTECEDENTES: En la demanda", SEGUNDA) == "antecedente"
    for frase in ("AGRAVIOS: I.", "Acusa la errónea valoración", "Objeta la inobservancia de jurisprudencia"):
        assert seccion(t, frase, SEGUNDA) == "alegato", frase
    # III y IV son considerandos (el bloque termina en el primer numeral que continúa la externa y no la interna)
    assert seccion(t, "En el presente caso se observa un vicio procesal", SEGUNDA) == "considerando_sin_clasificar"
    assert seccion(t, "Con sustento en las razones expuestas", SEGUNDA) == "considerando_sin_clasificar"
    al = [(a, b) for a, b, r in mapa(t, SEGUNDA).clasif.tramos if r == "alegato"]
    assert al == [(normalizar(t).find("II.- AGRAVIOS"), normalizar(t).find("III.- NULIDAD"))]


def test_sin_bloques_fuera_de_la_segunda_el_mismo_texto_no_cierra(encendido):
    # control negativo: la secuencia interna solo existe en un bloque «AGRAVIOS:» de la Segunda
    assert mapa(SEGUNDA_1431950, CONSTITUCIONAL).clasif.secuencia_cierra is False


def test_transcripcion_numerada_deja_el_fallo_sin_tramos(encendido):
    # sen-1-0007-1325213 5174 (y la forma de sen-1-0007-1290837 163906): «resolvió: "I.- …» con un «II.-» interno
    transcrita = ('INADMISIBILIDAD DEL RECURSO. Esta Sala en la sentencia No. 2024030445 resolvió: "I.- Del estudio de los autos '
                  'de logra desprender que la pretensión de la parte recurrente es que esta Sala ordene denegar el monto. II.- '
                  'Se declara inadmisible el recurso". El primer motivo es inadmisible.')
    c = mapa(tercera(MOTIVO_1303413, transcrita)).clasif
    assert c.secuencia_cierra is False and c.tramos == ()
    assert mapa(tercera(MOTIVO_1303413)).clasif.secuencia_cierra is True  # control: sin la transcripción, cierra


# sen-1-0006-1313540 III (pos. 11500-41600): tres motivos en un mismo considerando, cada uno con su veredicto.
VARIOS_1313540 = (
    "SEGUNDO RECURSO DE CASACIÓN. Primer motivo. Vicio in procedendo. Quebranto a los principios del debido proceso, de "
    "legalidad, derecho de defensa y tutela judicial efectiva. Reclama [Nombre 003], que en el segundo motivo de apelación, invocó "
    "vicios en el fundamento intelectivo y probatorio del fallo (confrontar folio 131, párrafo tercero). El alegato es "
    "inadmisible. Contexto introductorio sobre el trato jurídico, jurisprudencial y doctrinario actual del recurso de casación "
    "penal. En consecuencia, a la luz del articulado 467 y 469 párrafo último de la ordenanza procesal penal, se declara "
    "inadmisible el reclamo planteado. Segundo motivo. Vicio in procedendo ante el quebranto de los principios de "
    "fundamentación, debido proceso, legalidad, derecho de defensa y tutela judicial efectiva (confrontar folios 135 a 136 del "
    "expediente físico). El alegato resulta inadmisible. Mediante una técnica similar a la expuesta en los reclamos anteriores, "
    "la persona recurrente se decanta en atacar el fallo de primera instancia.")


def test_varios_motivos_en_un_considerando(encendido):
    t = tercera(VARIOS_1313540)
    rotulos = [r for _, _, r in mapa(t, HACIENDA).clasif.tramos]
    assert rotulos == ["alegato", "veredicto", "alegato", "veredicto"]
    assert seccion(t, "Contexto introductorio sobre el trato", HACIENDA) == "considerando_sin_clasificar"
    assert seccion(t, "Mediante una técnica similar", HACIENDA) == "considerando_sin_clasificar"


# --- antecedente -------------------------------------------------------------------------------------------------------

ENC_CONSTITUCIONAL = ("Exp: 25-008630-0007-CO Res. N° 2025010854 SALA CONSTITUCIONAL DE LA CORTE SUPREMA DE JUSTICIA. San José, a "
                      "las diez horas cinco minutos del ocho de abril de dos mil veinticinco. Recurso de amparo.\nResultando:\n1.- "
                      "Por escrito presentado en la Secretaría de la Sala la persona recurrente interpuso recurso de amparo.\n"
                      "Redacta el Magistrado Araya García; y,\nCONSIDERANDO:\nI.- OBJETO DEL RECURSO. La recurrente aduce que las "
                      "autoridades del Hospital México no le han realizado la cirugía prescrita. ")  # 1304923 / 1346460 5039
PT_CONSTITUCIONAL = "\nPor tanto:\nSe declara sin lugar el recurso. Notifíquese. Fernando Castillo V. Presidente Paul Rueda L."


@pytest.mark.parametrize("cabeza", ["II.- HECHOS PROBADOS. De relevancia para dirimir el presente recurso de amparo, se tienen "
                                    "por acreditados los siguientes: 1) La tutelada tiene 34 años de edad.",  # 1346460 5039
                                    "II.- Hechos probados. De importancia para la decisión de este asunto, se estiman como "
                                    "debidamente demostrados los siguientes hechos.",  # 1405414 20263
                                    ])
def test_antecedente_por_encabezado_exacto(encendido, cabeza):
    t = ENC_CONSTITUCIONAL + cabeza + " III.- SOBRE EL FONDO. Esta Sala estima que no lleva razón la recurrente." + PT_CONSTITUCIONAL
    assert seccion(t, "La recurrente aduce", CONSTITUCIONAL) == "antecedente"  # «OBJETO DEL RECURSO.»
    assert seccion(t, "los siguientes", CONSTITUCIONAL) == "antecedente"
    assert seccion(t, "Esta Sala estima", CONSTITUCIONAL) == "considerando_sin_clasificar"


def test_antecedentes_de_interes_no_es_antecedente(encendido):
    # sen-1-0007-1380421 III (pos. 25000): precedentes de la Sala bajo «ANTECEDENTES DE INTERÉS»
    t = (ENC_CONSTITUCIONAL + "II.- HECHOS PROBADOS. De relevancia se tienen por acreditados los siguientes hechos. "
         "III.- ANTECEDENTES DE INTERÉS. A efecto de resolver el presente proceso de habeas corpus, resulta menester observar lo "
         "que este Tribunal Constitucional ha señalado, al conocer casos similares al ahora planteado." + PT_CONSTITUCIONAL)
    assert seccion(t, "A efecto de resolver", CONSTITUCIONAL) == "considerando_sin_clasificar"
    assert seccion(t, "se tienen por acreditados", CONSTITUCIONAL) == "antecedente"  # control positivo en el mismo fallo


def test_la_cola_del_considerando_anterior_no_rotula_antecedente(encendido):
    # sen-1-0006-1432720 VIII/IX (pos. 45201): el VIII termina en «hechos probados…»; el IX es «Quinto motivo…»
    t = tercera("Se reprocha que se utilizan como base circunstancias con evidente quebranto del principio de intangibilidad de "
                "los hechos probados, a tenor de lo establecido en el numeral 471 del Código Procesal Penal.",
                "Quinto motivo. Falta de debida fundamentación en la determinación de la pena. El impugnante aduce que en "
                "apelación se impugnó la sanción.")
    assert seccion(t, "Quinto motivo", HACIENDA) != "antecedente"


# --- veredicto ---------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("cuerpo,frase", [
    # sen-1-0006-1286582 10875: tras el petitorio «Solicita se acoja el motivo…»
    ("Solicita se acoja el motivo, se recalifiquen los hechos a un solo delito de abusos deshonestos y se le imponga la pena de "
     "dos años. Se declara inadmisible el motivo de revisión. Es importante que se tome en consideración que el procedimiento "
     "de revisión es extraordinario.", "Se declara inadmisible el motivo de revisión."),
    # sen-1-1258-1283039 3956: prefijo «Para la mayoría»
    ("Gestiona como pretensión, que se declare con lugar el motivo y se ordene la realización de un nuevo juicio. Para la "
     "mayoría, el motivo debe ser declarado inadmisible: Una vez analizado el motivo incoado por el licenciado Quirós Wanters.",
     "Para la mayoría, el motivo debe ser declarado inadmisible:"),
    # sen-1-1258-1303413 3997: tras un petitorio
    (MOTIVO_1303413, "El primer motivo de casación se declara inadmisible."),
    # sen-1-0006-1285000 42545: inciso entre el verbo y el lexema
    ("Como petitoria solicita se case la resolución impugnada y se declare con lugar el motivo expuesto. El motivo es, para la "
     "mayoría, inadmisible. El séptimo reparo de casación de la fiscala denuncia un yerro.", "El motivo es, para la mayoría, inadmisible."),
    # sen-1-1258-1298612 8351: el petitorio no es veredicto, el «Se admite el reclamo.» que lo sigue sí
    ("Solicita se declare con lugar el recurso y se ordene el reenvío para una nueva sustanciación sobre dicho extremo.",
     None),
])
def test_veredicto_positivos(encendido, cuerpo, frase):
    t = tercera(cuerpo, "Se admite el reclamo. De conformidad con los ordinales 467, 468 y 469 del Código Procesal Penal.")
    if frase:
        assert seccion(t, frase) == "veredicto"
    assert seccion(t, "Se admite el reclamo.") == "veredicto"


@pytest.mark.parametrize("cuerpo,frase,despacho", [
    # sen-1-0006-1431195 2599: «Se …» sin sujeto de la lista
    ("Se rechaza la suspensión peticionada de la pena. Dicha medida, prevista solo como excepcional en el artículo 412.",
     "Se rechaza la suspensión", TERCERA),
    # sen-1-1258-1298612 8351: petitorio
    ("Solicita se declare con lugar el recurso y se ordene el reenvío para una nueva sustanciación.", "Solicita se declare", JUVENIL),
    # sen-1-0006-1303410 4577: la Procuraduría
    ("La procuradora de la ética pública dio contestación al recurso. En cuanto a este motivo señala que debe ser declarado "
     "inadmisible, toda vez que no cumple con los requisitos.", "En cuanto a este motivo", HACIENDA),
    # sen-1-1258-1283039 16211: una norma transcrita
    ("Al respecto, el numeral 462 propuesto señaló en lo que interesa: \"Si el recurso es admisible, el tribunal lo sustanciará "
     "y se pronunciará sobre el fondo\".", "\"Si el recurso es admisible", JUVENIL),
    # sen-1-0006-1371379 771: la sentencia recurrida transcrita
    ("Interponen recurso de casación contra la resolución número 2025-1063 (cfr. folio 129 a 141), la cual dispuso: \"Se "
     "declaran sin lugar los recursos de apelación planteados por las defensas técnicas.\"", "\"Se declaran sin lugar", HACIENDA),
])
def test_veredicto_negativos(encendido, cuerpo, frase, despacho):
    assert seccion(tercera(cuerpo), frase, despacho) != "veredicto"


def test_laudo_transcrito_no_es_veredicto_por_el_numero_de_parrafo(encendido):
    # sen-1-0004-1293163 6073: párrafo 188 del laudo arbitral; «188.» cierra la oración previa
    laudo = ("Examinados los fundamentos del recurso. B. PRONUNCIAMIENTO DESESTIMATORIO / 187. Se rechaza la pretensión de anular "
             "la totalidad de la asamblea general ordinaria del Condominio, celebrada el día veinticinco de enero del año dos mil "
             "veintidós. / 188. Se declaran sin lugar las pretensiones de la demanda deducidas contra MABINSA. / C. PRONUNCIAMIENTO")
    assert seccion(tercera(laudo), "Se declaran sin lugar las pretensiones", PRIMERA) != "veredicto"
    sin_numero = laudo.replace(" / 188.", "")  # control positivo: sin el número de párrafo, la forma sí calza
    assert seccion(tercera(sin_numero), "Se declaran sin lugar las pretensiones", PRIMERA) == "veredicto"


def test_transcripcion_con_introductor_no_es_veredicto(encendido):
    # sen-1-0006-1358914 15549: «…en los siguientes términos: "…Los dos motivos… Los motivos se declaran sin lugar.»
    intro = ("Sobre el particular, el Tribunal de Apelación de Sentencia Penal de Cartago abordó los cuestionamientos sobre la pena "
             "en los siguientes términos: \"…Los dos motivos anteriores se resuelven conjuntamente, por referirse ambos a la "
             "fundamentación de la pena. Los motivos se declaran sin lugar. En primer orden, en cuanto a los alegatos.")
    assert seccion(tercera(intro), "Los motivos se declaran sin lugar.", TERCERA) != "veredicto"
    sin_intro = intro.replace("en los siguientes términos: \"…", "de esta forma. ")
    assert seccion(tercera(sin_intro), "Los motivos se declaran sin lugar.", TERCERA) == "veredicto"  # control positivo


def test_cierre_transcrito_con_comilla_no_es_veredicto_y_su_gemelo_si(encendido):
    # sen-1-0007-1325213 6650 (cierre de una sentencia de la Sala transcrita) y 7624 (el cierre propio, sin comilla)
    lo = "Por lo anterior, lo procedente es que la accionante acuda a la vía ordinaria."
    t = (ENC_CONSTITUCIONAL + "II.- INADMISIBILIDAD DEL RECURSO. " + lo + " En consecuencia, el recurso es inadmisible y así se "
         "declara\".\nAl igual que el precedente en cuestión, no se observa una posición de poder. " + lo.replace("la accionante",
         "la parte accionante") + " En consecuencia, el recurso es inadmisible y así se declara.\nIII.- DOCUMENTACIÓN APORTADA "
         "AL EXPEDIENTE. Debe prevenir esta Sala a las partes." + PT_CONSTITUCIONAL)
    tn = normalizar(t)
    m = F.mapa_secciones(tn, CONSTITUCIONAL)
    primera = tn.find("En consecuencia, el recurso es inadmisible")
    assert F.seccion_en(m, primera) != "veredicto"
    assert F.seccion_en(m, tn.find("En consecuencia, el recurso es inadmisible", primera + 10)) == "veredicto"


def test_veredicto_de_cierre_no_cierra_alegato(encendido):
    con_cierre = MOTIVO_1303413.replace("El primer motivo de casación se declara inadmisible.", "Por lo expuesto, el reparo se declara sin lugar.")
    t = tercera(con_cierre)
    assert seccion(t, "Por lo expuesto, el reparo") == "veredicto"
    assert seccion(t, AGRAVIO) == "considerando_sin_clasificar"
    assert mapa(t).clasif.primer_veredicto is None  # el primer veredicto que no es de cierre: no hay
    assert seccion(tercera(MOTIVO_1303413), AGRAVIO) == "alegato"  # control positivo: sin conector de cierre, cierra el alegato


# --- alegato -----------------------------------------------------------------------------------------------------------

def test_alegato_positivo_cumple_las_cuatro_condiciones(encendido):
    t = tercera(MOTIVO_1303413)
    tn = normalizar(t)
    al = [(a, b) for a, b, r in mapa(t).clasif.tramos if r == "alegato"]
    assert al == [(tn.find("Primer motivo:"), tn.find("El primer motivo de casación"))]
    assert seccion(t, "Previo a establecer las razones") == "considerando_sin_clasificar"


def test_voz_de_la_sala_entre_encabezado_y_veredicto_veta_el_alegato(encendido):
    con_voz = MOTIVO_1303413.replace("Señala que dicho fallo", "Esta Sala advierte que dicho fallo")
    assert seccion(tercera(con_voz), AGRAVIO) == "considerando_sin_clasificar"  # condición 3


def test_candidato_sensible_previo_veta_el_alegato(encendido):
    # sen-1-0006-1371375 VI (sin la apertura 105413): «Por las razones que se dirán, el motivo no puede prosperar.»
    previo = MOTIVO_1303413.replace("Solicita se declare", "Por las razones que se dirán, el motivo no puede prosperar. Pide se declare")
    assert seccion(tercera(previo), AGRAVIO) == "considerando_sin_clasificar"  # condición 2


@pytest.mark.parametrize("cuerpo,despacho", [
    # sen-1-0006-1371375 VI sin la apertura (105413): solo queda el cierre «Por lo expuesto, el reparo se declara sin lugar.»
    ("En su noveno motivo la representante fiscal reprocha la inobservancia del artículo 142 del Código Procesal Penal. Critica "
     "que tal inobservancia menoscabó la participación del Ministerio Público. La fiscala de impugnaciones arguye la "
     "inobservancia de la garantía constitucional consagrada en el artículo 41. Esta Sala de Casación Penal ha sido clara en "
     "reconocer la relevancia que conlleva el respeto al debido proceso. Por lo expuesto, el reparo se declara sin lugar.", HACIENDA),
    # sen-1-1258-1283039 II sin la apertura (3956)
    ("En su primer motivo de casación, el recurrente reclama por \"inobservancia o errónea aplicación de un precepto legal "
     "procesal\" (cfr. folio 66). Gestiona como pretensión, que se declare con lugar el motivo. Una vez analizado el motivo "
     "incoado por el licenciado Quirós Wanters, es criterio de esta Cámara que éste debe ser declarado inadmisible. Así las "
     "cosas, con base en las consideraciones expuestas, se declara inadmisible el reclamo presentado.", JUVENIL),
    # sen-1-0006-1371379 III sin la apertura (7209)
    ("Primer motivo. Aquejan \"(…) Errónea aplicación del artículo 204 del Código Procesal Penal (…)\" (cfr. folio 246). Como "
     "pretensión solicitan se declare la ineficacia de la resolución recurrida. A) Consideraciones previas. Como reiteradamente "
     "lo ha indicado esta Sala, con voto de mayoría, la casación es extraordinaria. Con base en lo expuesto, y con fundamento en "
     "los artículos 467, 469 y 471 del Código Procesal Penal, se declara inadmisible el primer motivo del recurso de casación.", HACIENDA),
])
def test_sin_la_oracion_de_apertura_no_hay_alegato(encendido, cuerpo, despacho):
    m = mapa(tercera(cuerpo), despacho)
    assert not [r for _, _, r in m.clasif.tramos if r == "alegato"]


def test_veredicto_en_el_considerando_siguiente_no_cierra_alegato(encendido):
    # sen-1-0006-1391034 II-III: el encabezado en el II, el veredicto en el III
    ii = ("Primer motivo del procedimiento de revisión. Grave infracción a los deberes del juez. Sostiene que se le atribuyó "
          "responsabilidad penal a su defendido por hechos en los que no constaba participación. Como pretensión solicita que se "
          "anule la sentencia condenatoria.")
    iii = ("Por existir conexidad en sus reclamos, esta Cámara opta por resolver los motivos del procedimiento de revisión de "
           "manera conjunta. La demanda revisoria se declara inadmisible. Luego del análisis del líbelo de revisión.")
    t = tercera(ii, iii)
    assert not [r for _, _, r in mapa(t, HACIENDA).clasif.tramos if r == "alegato"]
    assert seccion(t, "La demanda revisoria se declara", HACIENDA) == "veredicto"
    junto = tercera(ii + " La demanda revisoria se declara inadmisible.")  # control positivo: mismo considerando
    assert seccion(junto, "Sostiene que se le atribuyó", HACIENDA) == "alegato"


def test_sobre_los_agravios_no_abre_bloque_y_recurso_de_la_parte_si(encendido):
    # sen-1-0034-1336510 II (5988, «RECURSO DE LA PARTE DEMANDADA:») y V (13688, «SOBRE LOS AGRAVIOS DE ORDEN PROCESAL:»)
    t = ("SALA SEGUNDA DE LA CORTE SUPREMA DE JUSTICIA. Proceso ordinario laboral; y,\nCONSIDERANDO: I.- ANTECEDENTES: El actor "
         "indicó en la demanda que prestó servicios para el demandado, como panadero.\nII.- RECURSO DE LA PARTE DEMANDADA: "
         "Argumenta que el fallo de instancia rechazó de plano el escrito del 11 de octubre de 2023.\nIII.- SOBRE EL FONDO: El "
         "reparo no es atendible.\nIV.- COSTAS: Se mantienen.\nV.- SOBRE LOS AGRAVIOS DE ORDEN PROCESAL: El ordinal 587 del "
         "Código de Trabajo se ocupa de los motivos de casación por razones procesales.\nPOR TANTO: Se declara sin lugar el "
         "recurso. Notifíquese.")
    assert seccion(t, "Argumenta que el fallo de instancia", SEGUNDA) == "alegato"
    assert seccion(t, "El ordinal 587", SEGUNDA) == "considerando_sin_clasificar"


# `tipo_resolucion` se prueba en test_conector_ficha.py, donde se expone.

# --- detector de `mayoria` sobre todos los textos de esta suite ------------------------------------------------------------

def _textos():
    return [(tercera(MOTIVO_1303413), JUVENIL), (tercera(VARIOS_1313540), HACIENDA), (SEGUNDA_1431950, SEGUNDA),
            (ENC_CONSTITUCIONAL + "II.- HECHOS PROBADOS. Se tienen por acreditados los hechos." + PT_CONSTITUCIONAL, CONSTITUCIONAL)]


# El test que recorre estos textos con `armar` y `verificar_cita` está en test_conector_verificar.py (archivo < 400 líneas).
