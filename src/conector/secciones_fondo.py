"""Rótulos del fondo de un fallo para el conector: solo lo seguro, nunca «criterio».

Función pura sobre el texto NORMALIZADO (posiciones 1 a 1 con el crudo: `normalizar` conserva el largo), sin BD ni `Mapa`, de modo
que otros módulos la puedan reutilizar. Rotula solo lo que NO es razonamiento de la Sala (`antecedente`, `alegato`) o un hecho de forma
(`veredicto`), donde la marca es explícita; lo demás es `considerando_sin_clasificar`. Cada regla está escrita para que, si
falla, falle hacia lo neutro. Las listas cerradas llevan la Sala de origen anotada. Guarda de estructura y
`tipo_resolucion` también viven aquí. Las listas se fijan antes de medirlas contra una muestra de fallos revisados a mano.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from src.conector.secciones_cortador import Considerando, cortar, oraciones
from src.indice.extracto import _dispositiva, _encabezados

# --- familias y emisión ----------------------------------------------------------------------------------------------
FAMILIAS = {"Sala Constitucional": "Constitucional", "Sala Primera de la Corte": "Primera", "Sala Segunda de la Corte": "Segunda",
            "Sala Tercera de la Corte": "Tercera", "Sala Tercera Materia Penal Juvenil": "Tercera",
            "Sala Tercera Penal de Hacienda y Función Pública": "Tercera"}
ROTULOS_FONDO = ("antecedente", "alegato", "veredicto")
EMISION_TOTAL = {f: frozenset(ROTULOS_FONDO) for f in ("Constitucional", "Primera", "Segunda", "Tercera")}
# Qué rótulo emite cada familia. Un rótulo cuya familia no pasó la medición NO se emite y cae a
# `considerando_sin_clasificar` (falla hacia lo neutro). El banco de juicio usa `EMISION_TOTAL` para ver los tramos del
# clasificador.
# Medición sobre una reserva de 60 fallos (κ >= 0,94): `antecedente`
# pasó en la Constitucional (59 oraciones, Wilson inf. 0,939) y en la Segunda (93, 0,960). `alegato` FALLÓ en Segunda y Tercera
# (títulos de motivo dentro del tramo); `veredicto` no llegó a los mínimos ni con el lote de ampliación (30 < 35). No encender
# nada aquí sin una medición nueva.
EMISION: dict[str, frozenset] = {"Constitucional": frozenset({"antecedente"}), "Primera": frozenset(),
                                 "Segunda": frozenset({"antecedente"}), "Tercera": frozenset()}

# --- veredicto -----------------------------------------------------------------------------------------------------
_ORD = (r"(?:primer[oa]?|segund[oa]|tercer[oa]?|cuart[oa]|quint[oa]|sext[oa]|s[eé]ptim[oa]|octav[oa]|noven[oa]|d[eé]cim[oa]"
        r"|[uú]nic[oa]|[uú]ltim[oa])")
# Sujetos (Tercera, Penal Juvenil, Penal de Hacienda; «demanda revisoria» del procedimiento de revisión).
_SUSTANTIVO = (r"(?:demanda\s+revisoria|motivo|reclamo|reparo|reproche|alegato|queja|agravio|recurso|procedimiento|demanda)s?"
               r"|gesti[oó]n|gestiones")
_SUJETO_ARTICULO = r"(?:el|la|los|las)\s+(?:(?:" + _ORD + r"|presente)\s+)?(?:" + _SUSTANTIVO + r")\b"
_LEXEMA = r"(?:admisibles?|inadmisibles?|de\s+recibo|atendibles?|inatendibles?|procedentes?|improcedentes?)"
# Inciso entre el verbo y el lexema: «El motivo es, para la mayoría, inadmisible.».
_INCISO = r"(?:,?\s*para\s+la\s+mayor[ií]a(?:\s+de\s+(?:la|esta)\s+Sala)?(?:\s*\([^)]{0,200}\))?\s*,?)?\s*"
_PREDICADO = (r"(?:\b(?:es|son|resulta|resultan)\b\s*" + _INCISO + _LEXEMA
              + r"|\bse\s+declaran?\b\s*" + _INCISO + r"(?:sin\s+lugar|con\s+lugar|(?:in)?admisibles?)"
              r"|\bse\s+admiten?\b|\bse\s+rechazan?\b|\bse\s+acogen?\b|\b(?:no\s+)?puede\s+prosperar\b|\b(?:no\s+)?prospera\b"
              r"|\bdeben?\s+ser\s+declarad[oa]s?\s*" + _INCISO + r"(?:" + _LEXEMA + r"|sin\s+lugar|con\s+lugar)"
              r"|\bdeben?\s+declararse\s*" + _INCISO + r"(?:" + _LEXEMA + r"|sin\s+lugar|con\s+lugar)"
              r"|\b(?:no\s+)?llevan?\s+raz[oó]n\b)")
# Conectores de cierre (Tercera): un veredicto que empieza así se rotula `veredicto`, nunca cierra un `alegato`.
_CIERRE = (r"(?:As[ií]\s+las\s+cosas|Por\s+lo\s+expuesto|Con\s+base\s+en\s+lo\s+expuesto|Con\s+fundamento\s+en\s+lo\s+expuesto"
           r"|En\s+consecuencia|Por\s+las\s+razones\s+expuestas|Por\s+lo\s+anterior|De\s+conformidad\s+con\s+lo\s+expuesto)")
_PREFIJO = (r"(?:(?:(?:Por\s+mayor[ií]a|Para\s+la\s+mayor[ií]a)(?:\s*\([^)]{0,200}\))?|Por\s+unanimidad|" + _CIERRE
            + r")\s*,?\s*)?")
_CON_SUJETO = re.compile(r"^" + _PREFIJO + r"(?:El|La|Los|Las)\s+(?:(?:" + _ORD + r"|presente)\s+)?(?:" + _SUSTANTIVO + r")\b"
                         r"(?P<comp>[^.:]{0,40}?)\s*,?\s*(?:no\s+)?" + _PREDICADO, re.I)
_CON_SE = re.compile(r"^" + _PREFIJO + r"[Ss]e\s+(?:admite|admiten|declara|declaran|rechaza|rechazan|acoge|acogen)\b", re.I)
_PREDICADO_RE = re.compile(_PREDICADO, re.I)
_SUJETO_RE = re.compile(r"\b" + _SUJETO_ARTICULO, re.I)
_ES_CIERRE = re.compile(r"^" + _CIERRE, re.I)
_SUBJUNTIVO = re.compile(r"\b(?:declare|declaren|acoja|acojan|admita|admitan|rechace|rechacen|declarar|acoger|admitir|rechazar)\b", re.I)
_EMPIEZA_MAL = re.compile(r"^(?:[\"'«“]|\d{1,4}\s*[.)]|[A-Za-z]\s*[.)]\s)")
_INTRODUCTOR = re.compile(r"resolvi[oó]\s*:|dispuso\s*:|dict[oó]\s+el\s+laudo|indic[oó]\s*:|se[nñ]al[oó]\s*:|en\s+lo\s+que\s+interesa"
                          r"|textualmente|lo\s+siguiente\s*:|en\s+los\s+siguientes\s+t[eé]rminos", re.I)
LARGO_INTRODUCTOR = 400
_PARTE_O_DECIR = re.compile(r"\b(?:solicita|pide|pretende|peticiona|se[nñ]ala\s+que|indica\s+que|considera\s+que|estima\s+que"
                            r"|la\s+recurrente|el\s+recurrente|la\s+defensa|la\s+fiscal[ií]a|el\s+Ministerio\s+P[uú]blico"
                            r"|la\s+Procuradur[ií]a|el\s+Tribunal\s+de\s+Apelaci[oó]n|el\s+ad\s+quem|el\s+a\s+quo|el\s+Tribunal\s+Arbitral)\b", re.I)
# Oración previa que termina en número de párrafo, letra de inciso o barra («/ 188.», «A.») en un laudo.
_PREVIA_PARRAFO = re.compile(r"(?:\b\d{1,4}|\b[A-Z])\s*\.$|/$")
_TERMINA_EN_COMILLA = re.compile(r"[\"']\s*[.:;]?$")  # «…y así se declara".»
MAX_VEREDICTO, MAX_SENSIBLE = 170, 250

# --- detector sensible (solo veta) ------------------------------------------------------------------------------------
_SENSIBLE_SUJETO = re.compile(r"\b(?:" + _SUSTANTIVO + r")\b", re.I)
_SENSIBLE_LEXEMA = re.compile(r"admisib|inadmisib|admit|sin\s+lugar|con\s+lugar|prosper|de\s+recibo|atendib|rechaz|acog|raz[oó]n", re.I)
_PETITORIO = re.compile(r"\b(?:solicita|pide|pretende|peticiona)\b|como\s+pretensi[oó]n", re.I)

# --- alegato y antecedente ---------------------------------------------------------------------------------
_ENCABEZADO_MOTIVO = re.compile(
    r"(?:" + _ORD + r"\s+(?:motivo|reclamo|reparo|reproche|agravio)\b|En\s+su\s+" + _ORD + r"\s+motivo\b"
    r"|En\s+el\s+" + _ORD + r"\s+(?:reclamo|reparo)\b|Como\s+" + _ORD + r"\s+reproche\b"
    r"|(?:Primero|Segundo|Tercero|Cuarto|Quinto|Sexto|S[eé]ptimo|Octavo|Noveno|D[eé]cimo)\s*\()", re.I)  # «Primero (…)»: Primera
# Voz de la Sala. Primera letra en cualquier caja: «Esta Sala…» también abre oración.
_VOZ_SALA = re.compile(r"\b[Ee]sta\s+Sala\b|\b[Ee]sta\s+C[aá]mara\b|\b[Ee]ste\s+Tribunal\b|\b[Ee]sta\s+jurisdicci[oó]n\b"
                       r"|\b[Uu]na\s+vez\s+examinad|\b[Uu]na\s+vez\s+analizad|\bAnalizad|\b[Ss]e\s+colige\b|\b[Ee]s\s+criterio\s+de\b"
                       r"|\b[Ee]stima\s+esta\b|\b[Cc]onsidera\s+esta\b")
_ANTECEDENTE = re.compile(r"\s*(?:OBJETO\s+DEL\s+RECURSO|ANTECEDENTES|HECHOS\s+PROBADOS|HECHOS\s+NO\s+PROBADOS"
                          r"|DOCUMENTACI[OÓ]N\s+APORTADA)\s*[:.]", re.I)  # exactos: «ANTECEDENTES DE INTERÉS» no

# --- guarda de estructura y tipo de resolución --------------------------------------------------------------
_OTRA_RESOLUCION = re.compile(r"\bRes\.|\bResoluci[oó]n\s+N\s*[°º]")
_RESULTANDO_PALABRA = re.compile(r"RESULTANDO|Resultando")
LARGO_OTRA_RESOLUCION = 1500
_ADMISIBILIDAD = re.compile(r"admit|admisib|inadmisib|inadmit", re.I)
_CON_O_SIN_LUGAR = re.compile(r"con\s+lugar|sin\s+lugar", re.I)


@dataclass(frozen=True)
class Clasificacion:
    """Tramos [(inicio, fin, rótulo)] ordenados y disjuntos dentro de [ini_cons, i_pt), y lo que se midió del fallo."""
    tramos: tuple = ()
    estructura: str = "confiable"  # "confiable" | "no_confiable"
    encabezados_dispositiva: int = 0
    tipo_resolucion: str = "sin_determinar"  # "admisibilidad" | "sin_determinar"
    primer_veredicto: int | None = None
    motivo_guarda: str | None = None  # "encabezados" | "otra_resolucion"
    secuencia_cierra: bool | None = None  # None: no hubo zona de considerandos que cortar


def familia(despacho: str | None) -> str | None:
    """Familia del despacho; None fuera de las seis Salas de la muestra (ahí no se emite nada del fondo)."""
    return FAMILIAS.get((despacho or "").strip())


def guarda(texto: str) -> tuple[str, int, str | None]:
    """(estructura, encabezados de dispositiva, motivo). Misma forma de encabezado que `extracto.por_tanto`."""
    enc = _encabezados(texto)
    if len(enc) >= 2:
        return "no_confiable", len(enc), "encabezados"
    if enc:
        for m in _OTRA_RESOLUCION.finditer(texto, enc[0]):
            if _RESULTANDO_PALABRA.search(texto, m.end(), m.end() + LARGO_OTRA_RESOLUCION):
                return "no_confiable", len(enc), "otra_resolucion"
    return "confiable", len(enc), None


def tipo_resolucion(dispositiva: str | None) -> str:
    """`admisibilidad` si la dispositiva trae un lexema de admisibilidad y no «con/sin lugar»; si no, `sin_determinar`."""
    if not dispositiva:
        return "sin_determinar"
    return "admisibilidad" if _ADMISIBILIDAD.search(dispositiva) and not _CON_O_SIN_LUGAR.search(dispositiva) else "sin_determinar"


def veredicto_preciso(texto: str, a: int, b: int, previa: str) -> tuple[bool, bool, str | None]:
    """(¿veredicto preciso?, ¿de cierre?, motivo de exclusión) de la oración [a, b) con su oración previa."""
    s = texto[a:b].strip()
    if not s or len(s) > MAX_VEREDICTO or not s[0].isupper() and s[0] not in "\"'":
        return False, False, None
    m = _CON_SUJETO.match(s)
    forma = bool(m and " que " not in f" {m.group('comp')} ") or bool(_CON_SE.match(s) and _PREDICADO_RE.search(s)
                                                                       and _SUJETO_RE.search(s))
    if not forma:
        return False, False, None
    if _SUBJUNTIVO.search(s):
        return False, False, "subjuntivo o infinitivo"
    if _EMPIEZA_MAL.match(s):
        return False, False, "empieza con comilla, párrafo o inciso"
    if _INTRODUCTOR.search(texto, max(0, a - LARGO_INTRODUCTOR), a):
        return False, False, "introductor de transcripción"
    if _PARTE_O_DECIR.search(s):
        return False, False, "parte u órgano en la oración"
    previa = previa.rstrip()
    if _PREVIA_PARRAFO.search(previa):
        return False, False, "previa termina en párrafo, inciso o barra"
    if _TERMINA_EN_COMILLA.search(s):
        return False, False, "termina con comilla"
    if previa.endswith(":"):
        return False, False, "previa termina en dos puntos"
    return True, bool(_ES_CIERRE.match(s)), None


def sensible(oracion: str) -> bool:
    """Candidato del detector sensible: sujeto de la lista y lexema de decisión en cualquier parte, sin petitorio."""
    s = oracion.strip()
    return len(s) <= MAX_SENSIBLE and bool(_SENSIBLE_SUJETO.search(s)) and bool(_SENSIBLE_LEXEMA.search(s)) and not _PETITORIO.search(s)


def _encabezado_motivo(oracion: str) -> bool:
    s = oracion.lstrip()
    return bool(_ENCABEZADO_MOTIVO.match(s[:90])) and not s.upper().startswith("SOBRE")


def _tramos_de(texto: str, c: Considerando, diag: Counter) -> list[tuple[int, int, str]]:
    """Tramos de un considerando: `antecedente` por encabezado exacto, bloque de la Segunda, o veredicto y alegato."""
    if _ANTECEDENTE.match(texto, c.cuerpo):
        return [(c.inicio, c.fin, "antecedente")]
    if c.bloque:  # condición 4: el bloque va hasta el fin del considerando, con la condición 3 sobre todo el bloque
        if _VOZ_SALA.search(texto, c.cuerpo, c.fin):
            diag["alegato cae: voz de la Sala en el bloque"] += 1
            return []
        return [(c.inicio, c.fin, "alegato")]
    ors, salida, pendiente = oraciones(texto, c.cuerpo, c.fin), [], None
    for k, (oa, ob) in enumerate(ors):
        previa = texto[ors[k - 1][0]:ors[k - 1][1]] if k else ""
        es, cierre, excl = veredicto_preciso(texto, oa, ob, previa)
        if excl:
            diag["veredicto excluido: " + excl] += 1
        if es:
            salida.append((oa, ob, "veredicto_cierre" if cierre else "veredicto"))
            if pendiente is not None and not cierre:
                pa, pk = pendiente
                primero = next((j for j in range(pk + 1, k + 1) if sensible(texto[ors[j][0]:ors[j][1]])), None)
                if primero != k:  # condición 2
                    diag["alegato cae: candidato sensible previo"] += 1
                elif _VOZ_SALA.search(texto, pa, oa):  # condición 3
                    diag["alegato cae: voz de la Sala"] += 1
                else:
                    salida.append((pa, oa, "alegato"))
            pendiente = None  # un veredicto de cierre anula el encabezado pendiente y nunca cierra un alegato
        elif _encabezado_motivo(texto[oa:ob]):
            pendiente = (oa, k)
    return salida


def clasificar(texto: str, despacho: str | None, i_pt: int, ini_cons: int, fin_palabra: int | None = None,
               emision: dict | None = None, diagnostico: Counter | None = None) -> Clasificacion:
    """Clasificación del fondo de `texto` (normalizado). `i_pt`: dispositiva de `extracto.por_tanto`; `ini_cons`: el
    «Considerando» después del resultando (-1 si no hay). `fin_palabra`: fin de esa palabra (por defecto, la busca)."""
    diag = diagnostico if diagnostico is not None else Counter()
    estructura, n_enc, motivo = guarda(texto)
    if estructura == "no_confiable":
        return Clasificacion((), estructura, n_enc, "sin_determinar", None, motivo, None)
    tipo = tipo_resolucion(_dispositiva(texto, i_pt) if i_pt >= 0 else None)
    fam = familia(despacho)
    base = Clasificacion((), estructura, n_enc, tipo, None, None, None)
    if fam is None or i_pt < 0 or ini_cons < 0 or ini_cons >= i_pt:
        return base
    if fin_palabra is None:
        fin_palabra = ini_cons + len(re.match(r"\s*\w+\s*[:.\-–]?", texto[ini_cons:ini_cons + 40]).group(0))
    cons = cortar(texto, ini_cons, i_pt, fin_palabra, con_bloques=fam == "Segunda")
    if cons is None:
        diag["secuencia no cierra"] += 1
        return Clasificacion((), estructura, n_enc, tipo, None, None, False)
    crudos = [t for c in cons for t in _tramos_de(texto, c, diag)]
    emite = (EMISION if emision is None else emision).get(fam, frozenset())
    tramos = tuple(sorted((a, b, "veredicto" if r == "veredicto_cierre" else r) for a, b, r in crudos
                          if ("veredicto" if r == "veredicto_cierre" else r) in emite))
    primero = next((a for a, _, r in sorted(crudos) if r == "veredicto"), None) if "veredicto" in emite else None
    return Clasificacion(tramos, estructura, n_enc, tipo, primero, None, True)


def tramos_crudos(texto: str, despacho: str | None, i_pt: int, ini_cons: int, fin_palabra: int | None = None) -> Clasificacion:
    """La clasificación con todos los rótulos encendidos (`EMISION_TOTAL`): la usan el banco de juicio y la medición."""
    return clasificar(texto, despacho, i_pt, ini_cons, fin_palabra, emision=EMISION_TOTAL)
