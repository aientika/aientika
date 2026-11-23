"""Filtro de clase y extracto para la capa semántica del índice.

El extracto tiene tres partes: objeto del recurso (para buscar por hechos), fondo de mayoría hasta el primer ENCABEZADO de
disidencia (una mención no corta) y el «por tanto» de mayoría, que va siempre. El texto que se guarda en la base no se
toca: `normalizar` se aplica al vuelo. Reglas medidas sobre una muestra de sentencias; son reglas para
decidir qué embeber, no para calificar un fallo.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

LARGO_OBJETO = 1000
LARGO_POR_TANTO = 1800
CARACTERES_POR_TOKEN = 3.5  # conservador para español; la cifra real sale de countTokens

# Encabezado de la dispositiva, en cualquier caja y en texto corrido (la Sala Tercera escribe «Por Tanto:» a media línea): «POR TANTO»
# en mayúsculas, «Por tanto» / «Por Tanto» / «por tanto» seguido de «:» o «.», o «Por tanto» al inicio de línea si no sigue
# coma. Una mención dentro de una oración («…y, por tanto, está sometido a…») NO es encabezado (el extracto se quedaba
# con el voto salvado plantilla y sin la dispositiva).
# Los tribunales (Trabajo de San José, Pérez Zeledón, Cartago, Puntarenas, etc.) cierran con «PARTE DISPOSITIVA» (con o sin «:»), no
# con «POR TANTO»: es el mismo encabezado (sin esto se tomaba el «POR TANTO» transcrito de primera instancia y el
# extracto decía lo contrario de lo que resolvió el tribunal). En minúscula solo vale con «:».
# El Juzgado de Familia Especializado en Apelaciones de Pensiones Alimentarias escribe «P O R T A N T O:» con letras separadas
# (también se tomaba el «POR TANTO» transcrito de primera instancia). Solo en mayúscula y con límites de palabra, para que una
# letra suelta pegada a otra palabra no cuente.
# También cubre erratas frecuentes: «PARTE DISPOSTIVA / DISPOSITVA / DIAPOSITIVA» (el extracto tomaba el «CON LUGAR» del juzgado
# y el tribunal había revocado). Estos son los encabezados FUERTES; abajo se agrega uno débil.
_POR_TANTO_FUERTE = re.compile(r"POR\s+TANTO|PARTE\s+DISPOSITIVA|\b[Pp]or\s+[Tt]anto\s*[:.]|\bParte\s+[Dd]ispositiva\s*[:;]"
                               r"|(?<![a-záéíóúñ,]\s)Parte\s+[Dd]ispositiva\s+(?=[A-ZÁÉÍÓÚÑ][a-záéíóúñ])"
                               r"|^\s*Por\s+[Tt]anto\b(?!\s*,)"
                               r"|\bP\s+O\s+R\s+T\s+A\s+N\s+T\s+O\b"
                               r"|PARTE\s+(?:DISPOS(?:TIVA|ITVA)|DIAPOSITIVA)\b", re.M)
# Encabezado DÉBIL: «…agravio. Por Tanto ⏎ Se acogen…», «…costas. Por tanto Se acoge…», «Por Tanto; Se deniegan…», a media
# línea y sin signo. Sin esto ganaba el POR TANTO transcrito del juzgado o del acto administrativo (el extracto decía «CON LUGAR
# la demanda» y el tribunal la había declarado sin lugar). Exige fin de oración (o signo, comilla, paréntesis, guion) o salto de
# línea justo antes, para no confundirlo con la sentencia corregida pegada al final de una corrección de error material, y no le
# gana a un encabezado fuerte posterior (filtro en por_tanto).
_ANTES_DEBIL = r"(?:(?<=[.;:!?)\]\"”»\-–]\s)|(?<=[.;:!?)\]\"”»\-–]\s\s)|(?<=\n)|(?<=\n\s))"
_POR_TANTO = re.compile(_POR_TANTO_FUERTE.pattern
                        + r"|" + _ANTES_DEBIL + r"Por\s+[Tt]anto\s*;"
                        + r"|" + _ANTES_DEBIL + r"Por\s+[Tt]anto\s+(?=[A-ZÁÉÍÓÚÑ][a-záéíóúñ])", re.M)
# Pie de firmas de los tribunales: «… - JUEZ/A DECISOR/A», «JUEZ/A TRAMITADOR/A», «Código Verificador». NO se usa «Teléfonos:» ni
# «MAGISTRADO/A»: el pie de las Salas también los trae y recortarlo movía el extracto de muchos fallos de Sala sin
# corregir nada. Con estos marcadores el recorte casi no toca a las Salas y sí a los tribunales.
_PIE_TRIBUNAL = re.compile(r"(?:DECISOR|TRAMITADOR)/A|C[oó]digo\s+Verificador")
_NOTIFICACION = re.compile(r"Notif[ií]quese|NOTIF[ÍI]QUESE|Comun[ií]quese|COMUN[ÍI]QUESE|H[áa]gase\s+saber", re.I)
LARGO_FIRMAS = 600
_FIN_DE_ORACION = re.compile(r"\.[-–]*(?=\s)")
_PARTE_DISPOSITIVA = re.compile(r"PARTE\s+DISPOSITIVA|Parte\s+[Dd]ispositiva|PARTE\s+(?:DISPOS(?:TIVA|ITVA)|DIAPOSITIVA)\b")
# Lo que antecede a una transcripción: «…el Juzgado resolvió: "POR TANTO…"», «dispuso: POR TANTO…». La resolución de primera
# instancia (o de otra sala) transcrita no es la dispositiva de quien firma. Con o sin comilla.
_ANTES_DE_TRANSCRIPCION = re.compile(
    r"(?:resolvi[oó]|resolvieron|dispuso|dispusieron|dispone|resuelve|fall[oó]|indic[oó]|estableci[oó]|concluy[oó]|orden[oó]"
    r"|decidi[oó])\s*(?:lo\s+siguiente\s*)?[:,]?\s*[\"'«“]*\s*(?:\(\s*(?:\.\.\.|…)\s*\)|\.\.\.|…)?\s*$", re.I)
# Caso especial: «resolvió: "(…) PARTE DISPOSITIVA…» es la resolución transcrita aunque la elipsis separe la comilla del encabezado.
# Disidencia en cualquier lugar: «VOTO SALVADO» en mayúsculas o «Voto salvado de(l) la Magistrad…» (la Sala Tercera lo pone a
# media línea, tras las firmas). La mención «con voto salvado de la magistrada…» va en minúscula y no cuenta.
_MARCA_DISIDENCIA = re.compile(r"VOTO\s+SALVADO|Voto\s+salvado\s+(?:del?|de\s+la)\s+[Mm]agistrad|NOTA\s+(?:DEL|DE\s+LA)\s+MAGISTRAD"
                               r"|Nota\s+(?:del|de\s+la)\s+[Mm]agistrad|Nota\s+separada|NOTA\s+SEPARADA")
# Verbo dispositivo en los primeros caracteres de la dispositiva; «se + verbo» cubre casi todas («Se declara…», «Se remite…»).
_VERBO_DISPOSITIVO = re.compile(
    r"\bse\s+[a-záéíóúñ]{4,}|\b(?:declara|declina|rechaza|anula|confirma|absuelve|condena|admite|inadmisible|ordena|archiv|resuelve"
    r"|revoca|casa|acoge|acuerda|dispone|pase|remit|devu[eé]lv|est[eé]se|\w+[eé]ese|no\s+ha\s+lugar|con\s+lugar|sin\s+lugar"
    r"|proced[ae]\b|itin[eé]r)", re.I)
# Los verbos incluyen «Itinérese el expediente…» y «Antes de resolver…, proceda el Juzgado…», que no cedían ante el POR TANTO transcrito.
# `_MINORIA` detecta la dispositiva del voto de minoría con su propio POR TANTO después del de mayoría («POR TANTO: En voto de
# minoría me inclino…»); un «Voto salvado del juez X» a media línea no es marca.
_MINORIA = re.compile(r"^\W*(?:P\s*O\s*R\s+T\s*A\s*N\s*T\s*O|Por\s+[Tt]anto|PARTE\s+DISPOSITIVA|Parte\s+[Dd]ispositiva)?\W*"
                      r"(?:En\s+)?(?:voto|criterio|posici[oó]n)\s+(?:de\s+)?minor[ií]a", re.I)
LARGO_VERBO = 400
# El marcador del fondo («caso concreto», casi siempre una mención dentro de una oración) solo se descarta si cae tras la mitad del
# fallo, se saltarían al menos SALTO_FONDO_MAXIMO caracteres Y la firma es de tribunal (_FORMA_TRIBUNAL). Sin esas condiciones la
# regla movía el fondo de muchos fallos de Sala sin una corrección que se pudiera confirmar leyendo, y el extracto de las Salas
# ya estaba validado.
SALTO_FONDO_MAXIMO = 15_000
# Firma de tribunal en el final del fallo (jueces de apelación, decisores, tramitadores, código verificador). Casi ningún fallo de
# Sala la tiene; los de tribunales sí.
_FORMA_TRIBUNAL = re.compile(
    r"Jue(?:z|za|ces|zas)(?:\s+y\s+[Jj]ue(?:z|za|ces|zas))?\s+(?:de|del)\s+(?:Tribunal\s+de\s+)?[Aa]pelaci[oó]n"
    r"|(?:DECISOR|TRAMITADOR)/A|C[oó]digo\s+Verificador|Jueces?\s+Decisores?|Jueces?\s+de\s+Juicio")
_NOTIFIQUESE = re.compile(r"Notif[ií]quese")
# Encabezado de disidencia: al inicio de línea, con su numeral opcional («VIII.- VOTO SALVADO…»). Una mención dentro de una
# oración («…el voto salvado de la Sala Nº 2012-008421») no es encabezado y no corta.
_ENCABEZADO_DISIDENCIA = re.compile(
    r"^\s*(?:[IVXLC]+|\d+)?\s*[.\-–)]*\s*(?:voto\s+salvado|nota\s+(?:del|de\s+la)\s+magistrad|nota\s+separada"
    r"|razones\s+(?:diferentes|adicionales))", re.I | re.M)
_CORTES_DISPOSITIVA = ("salva el voto", "salvan el voto", "salvamos el voto", "pone nota", "consigna nota",
                       "razones diferentes", "razones adicionales", "voto salvado", "redacta el", "redacta la")
_INICIO_FONDO = ("sobre el fondo", "caso concreto", "sobre el caso", "análisis del caso", "analisis del caso")
_TRAMITE = re.compile(r"^\s*documentaci[oó]n aportada al expediente.*$", re.I | re.M)
_FORMAL = ("artículo 42", "articulo 42")
_PREVENCION = ("prevenc", "subsan", "no cumpl")
_EJECUCION = ("archív", "archiv", "estese", "estése", "no ha lugar", "amplía el plazo", "amplia el plazo")
_TIPOGRAFIA = str.maketrans({" ": " ", " ": " ", " ": " ", "“": '"', "”": '"', "„": '"', "«": '"',
                             "»": '"', "‘": "'", "’": "'", "º": "°"})


def normalizar(texto: str) -> str:
    """Espacios duros y comillas tipográficas a sus formas simples, «º» a «°». Se aplica al vuelo, nunca al texto guardado."""
    return texto.translate(_TIPOGRAFIA)


def _encabezados(texto: str) -> list[int]:
    """Posiciones de los encabezados de dispositiva propios: se descartan los transcritos (entre comillas o tras «resolvió:»).

    «PARTE DISPOSITIVA» no se descarta por una comilla pegada (suele ser la que CIERRA la transcripción del juzgado que la
    precede); sí por «resolvió:» / «dispuso:» delante.
    """
    return [m.start() for m in _POR_TANTO.finditer(texto)
            if not _transcrito(texto, m.start(), con_comilla=not _PARTE_DISPOSITIVA.match(texto, m.start()))]


def _transcrito(texto: str, i: int, con_comilla: bool = True) -> bool:
    """¿El «por tanto» en `i` abre una resolución transcrita? «resolvió:» / «dispuso:» justo antes, o (si `con_comilla`) comilla pegada.

    El respaldo de la mención en minúscula pasa `con_comilla=False`: ahí una comilla sola no descarta, porque el tribunal también
    transcribe su propia resolución oral o su corrección («…para que se lea de la siguiente forma: "POR TANTO: 1.- Por mayoría…»)
    y esas SÍ son la dispositiva (43 de 19.500 tribunales 2025 se perdían con la regla de la comilla).
    """
    antes = texto[max(0, i - 80):i].rstrip(" \t")  # un salto de línea tras la comilla cierra la cita
    return (con_comilla and antes[-1:] in ('"', "'", "«", "“")) or bool(_ANTES_DE_TRANSCRIPCION.search(antes))


def _marcas_disidencia(texto: str) -> list[int]:
    """Posiciones ordenadas de toda marca de disidencia (encabezado de línea o «VOTO SALVADO» a media línea)."""
    return sorted(m.start() for f in (_ENCABEZADO_DISIDENCIA, _MARCA_DISIDENCIA) for m in f.finditer(texto))


def _apendice_de_disidencia(texto: str, encabezados: list[int]) -> int:
    """Posición donde empieza el voto salvado que sigue a la dispositiva ya firmada; len(texto) si no hay.

    Es la primera marca de disidencia que viene después del ÚLTIMO encabezado y de un «Notifíquese» posterior a él: la mayoría ya
    cerró (Sala Tercera: «Por Tanto… Notifíquese. [firmas] VOTO SALVADO…»). Una disidencia con otro encabezado después
    (Constitucional: «III.- VOTO SALVADO…» y luego el POR TANTO final; o dos resoluciones pegadas en un mismo texto) es parte del
    cuerpo y no corta.
    """
    for d in _marcas_disidencia(texto):
        previos = [h for h in encabezados if h < d]
        if previos and previos[-1] == encabezados[-1] and _NOTIFIQUESE.search(texto, previos[-1], d):
            return d
    return len(texto)


def _dispositiva(texto: str, i: int) -> str:
    """Desde el encabezado en `i` hasta el primer corte (salvamento, nota, redactor) o el largo máximo."""
    cola = texto[i:i + LARGO_POR_TANTO]
    bajo = cola.lower()
    cortes = [bajo.find(c) for c in _CORTES_DISPOSITIVA if bajo.find(c) > 0]
    return _sin_pie((cola[:min(cortes)] if cortes else cola).strip())


def _sin_pie(disp: str) -> str:
    """Quita las firmas y el pie de los tribunales (códigos, «JUEZ/A DECISOR/A», «TRAMITADOR/A») que siguen a la dispositiva.

    Corta en el último «Notifíquese» / «Comuníquese» / «Hágase saber» que precede al primer marcador de pie y a no más de
    LARGO_FIRMAS de él; si no hay, en el último punto antes del pie (con los códigos y nombres de los jueces a continuación,
    como en sen-1-0034-1285354). Sin marcador de pie o sin un corte a esa distancia, no toca nada (mejor ruido que perder dispositiva).
    """
    pie = _PIE_TRIBUNAL.search(disp)
    if not pie:
        return disp
    previas = list(_NOTIFICACION.finditer(disp, 0, pie.start()))
    if previas and pie.start() - previas[-1].end() <= LARGO_FIRMAS:
        return disp[:previas[-1].start()].rstrip(" .-–")
    puntos = list(_FIN_DE_ORACION.finditer(disp, max(0, pie.start() - LARGO_FIRMAS), pie.start()))
    return disp[:puntos[-1].start() + 1] if puntos else disp


def por_tanto(texto: str) -> tuple[int, str]:
    """(posición, dispositiva de mayoría con su caja original). (-1, '') si no hay «por tanto» ni «PARTE DISPOSITIVA».

    Los encabezados son «POR TANTO» y «PARTE DISPOSITIVA» (tribunales); se descartan los de una resolución transcrita («resolvió:
    "POR TANTO…"»). Vale el último encabezado que no esté en un apéndice de disidencia (el voto salvado que sigue a la dispositiva firmada; el
    plantilla de la Sala Tercera trae «…y, por tanto, está sometido a…» y no puede ganar). Un voto salvado en el cuerpo, antes del
    POR TANTO (Constitucional, Primera, Segunda), no corta: ahí el POR TANTO final es el de mayoría. Un candidato sin verbo dispositivo cede
    ante el anterior; si ninguno lo tiene, vale el último encabezado. Sin encabezado, la última mención en minúscula ANTERIOR
    a cualquier marca de disidencia, y solo si lo que sigue trae verbo dispositivo.
    """
    todos = _encabezados(texto)
    corte = _apendice_de_disidencia(texto, todos)
    zona = [h for h in todos if h < corte] or todos
    zona = [h for h in zona if not _MINORIA.match(_dispositiva(texto, h))] or zona
    # Un «Por tanto» débil no le gana a un encabezado fuerte posterior: puede ser parte de una resolución transcrita entera (la
    # dispositiva real, por ejemplo «Desglósese…», puede no traer un verbo de la lista y cedía).
    fuertes = [h for h in zona if _POR_TANTO_FUERTE.match(texto, h)]
    zona = [h for h in zona if not fuertes or h >= fuertes[-1] or h in fuertes]
    for h in reversed(zona):
        disp = _dispositiva(texto, h)
        # «PARTE DISPOSITIVA» es siempre la del tribunal que firma: vale aunque su verbo no esté en la lista («no corresponde a este
        # Tribunal conocer…») y no cede ante el «POR TANTO» transcrito de primera instancia que lo precede.
        if _VERBO_DISPOSITIVO.search(disp[:LARGO_VERBO]) or _PARTE_DISPOSITIVA.match(texto, h):
            return h, disp
    if zona:
        return zona[-1], _dispositiva(texto, zona[-1])
    marcas = _marcas_disidencia(texto)
    previo = texto[:marcas[0] if marcas else len(texto)].lower()
    i = previo.rfind("por tanto")
    while i >= 0 and _transcrito(texto, i, con_comilla=False):  # la mención suelta también puede ser la de una resolución transcrita
        i = previo.rfind("por tanto", 0, i)
    if i < 0:
        return -1, ""
    disp = _dispositiva(texto, i)
    return (i, disp) if _VERBO_DISPOSITIVO.search(disp[:LARGO_VERBO]) else (-1, "")


def clase_f2(texto: str) -> str:
    """'embeber', 'rechazo_formal', 'ejecucion' (gestión sin criterio) o 'sin_por_tanto'."""
    _, disp = por_tanto(texto)
    if not disp:
        return "sin_por_tanto"
    d = disp.lower()
    if "rechaz" in d:
        bajo = texto.lower()
        if any(k in bajo for k in _FORMAL) and any(k in bajo for k in _PREVENCION):
            return "rechazo_formal"
        return "embeber"
    if "con lugar" in d or "sin lugar" in d:
        return "embeber"
    if any(k in d for k in _EJECUCION):
        return "ejecucion"
    return "embeber"  # «otro» y mixtos se embeben


@dataclass
class Extracto:
    """Las tres partes del extracto y cómo se armó."""
    objeto: str
    fondo: str
    por_tanto: str
    corte_en_disidencia: bool
    con_marcador_fondo: bool

    def texto(self) -> str:
        return "\n\n".join(p for p in (self.objeto, self.fondo, self.por_tanto) if p)

    def tokens_estimados(self) -> int:
        return int(len(self.texto()) / CARACTERES_POR_TOKEN)


# Encabezado RESULTANDO: en mayúscula, «Resultando:» con signo, o al inicio de línea. El gerundio en medio de una frase («…resultando
# esto en meras manifestaciones…») NO es encabezado (anclaba el objeto en una frase suelta). «considerando» se busca como subcadena:
# cambiarlo movía el fondo de muchos fallos de Sala sin una corrección que se pudiera confirmar leyendo.
_RESULTANDO = re.compile(r"RESULTANDO|\bResultando\s*(?:[:.\-–\n]|\d)|^\s*[Rr]esultando\b", re.M)
# Encabezado CONSIDERANDO, solo para saber dónde arranca el análisis cuando «caso concreto» cae al final de un fallo largo.
_CONSIDERANDO = re.compile(r"CONSIDERANDO|\bConsiderando\s*[:.\-–]|^\s*[Cc]onsiderando\b", re.M)


def _inicio_objeto(texto: str, bajo: str, limite: int) -> int:
    """Posición donde empieza el objeto: «objeto del recurso», el encabezado RESULTANDO o «considerando»; 0 si no hay."""
    resultando = _RESULTANDO.search(texto)
    candidatos = [bajo.find("objeto del recurso"), resultando.start() if resultando else -1, bajo.find("considerando")]
    return next((i for i in candidatos if 0 <= i < limite), 0)


def extraer(texto: str) -> Extracto:
    """Arma el extracto. No recorta por largo: eso lo hace `ajustar`, según el modelo."""
    i_pt, disp = por_tanto(texto)
    fin = i_pt if i_pt > 0 else len(texto)
    encabezado = next((m for m in _ENCABEZADO_DISIDENCIA.finditer(texto, 0, fin)), None)
    if encabezado:
        fin = encabezado.start()
    bajo = texto.lower()
    i_obj = _inicio_objeto(texto, bajo, fin)
    fin_objeto = min(i_obj + LARGO_OBJETO, fin)
    if not bajo.startswith("considerando", i_obj):  # el objeto no invade los considerandos (trámite, fondo)
        c = bajo.find("considerando", i_obj + 1, fin_objeto)
        fin_objeto = c if c > 0 else fin_objeto
    objeto = _TRAMITE.sub("", texto[i_obj:fin_objeto]).strip()
    marcas = [bajo.find(m, fin_objeto, fin) for m in _INICIO_FONDO]
    marcas = [m for m in marcas if m >= 0]
    if marcas:
        ini = min(marcas)
        if (ini > len(texto) // 2 and ini - fin_objeto >= SALTO_FONDO_MAXIMO
                and _FORMA_TRIBUNAL.search(texto, max(0, len(texto) - 3000))):  # «caso concreto» al final deja fuera el análisis
            c = _CONSIDERANDO.search(texto, fin_objeto, fin)
            ini = c.start() if c and c.start() < ini else fin_objeto
    else:
        c = bajo.find("considerando", fin_objeto, fin)
        ini = c if c >= 0 else fin_objeto
    fondo = _TRAMITE.sub("", texto[max(ini, fin_objeto):fin]).strip()
    return Extracto(objeto, fondo, disp, encabezado is not None, bool(marcas))


def ajustar(ext: Extracto, max_tokens: int) -> tuple[str, bool]:
    """(texto que cabe en `max_tokens`, ¿se recortó?). Recorta el fondo POR EL MEDIO; objeto y «por tanto» quedan completos."""
    completo = ext.texto()
    if ext.tokens_estimados() <= max_tokens:
        return completo, False
    fijo = len(ext.objeto) + len(ext.por_tanto) + 4
    cupo = int(max_tokens * CARACTERES_POR_TOKEN) - fijo - 7
    if cupo <= 0:
        raise ValueError("objeto y «por tanto» no caben en el límite del modelo: no se embebe en silencio")
    mitad = cupo // 2
    fondo = ext.fondo[:mitad] + " [...] " + ext.fondo[len(ext.fondo) - mitad:]
    return Extracto(ext.objeto, fondo, ext.por_tanto, ext.corte_en_disidencia, ext.con_marcador_fondo).texto(), True
