"""Fragmentos de un fallo para el conector: ventanas de <= 600 caracteres con su sección, «por tanto» recortado y enlace.

El conector nunca devuelve el texto íntegro: solo ventanas cortas, cada una rotulada con la sección del fallo en que cae
(`SECCIONES`). NINGÚN rótulo afirma criterio de la Sala: lo
que no se pudo clasificar sale `considerando_sin_clasificar`. La dispositiva y las disidencias salen de las reglas de
`src/indice/extracto.py`, más las formas de voto salvado de este módulo, que se agregan AQUÍ; los tramos
del fondo, de `secciones_fondo.clasificar`. Nunca se usa `ts_headline` sobre fallos enteros (hasta 1,46 M de caracteres): las
ventanas se cortan en Python sobre el texto ya traído. El texto pasa por `normalizar` (comillas y espacios tipográficos).
"""

from __future__ import annotations

import bisect
import re
import unicodedata
from dataclasses import dataclass, field

from src.conector.secciones_fondo import Clasificacion, clasificar
from src.indice.extracto import (_CONSIDERANDO, _CORTES_DISPOSITIVA, _RESULTANDO, LARGO_POR_TANTO,
                                        _marcas_disidencia, extraer, normalizar, por_tanto)

URL_FALLO_OFICIAL = "https://nexuspj.poder-judicial.go.cr/document/"
MAX_FRAGMENTO = 600
MAX_POR_TANTO = 400
# Resultado medido sobre la dispositiva elegida en fallos que la guarda marca como de estructura no confiable.
MEDIDA_GUARDA = "acertó en 40 de 40 fallos de una muestra al azar"
SECCIONES = ("encabezado_del_fallo", "resultando", "considerando_sin_clasificar", "antecedente", "alegato", "veredicto",
             "por_tanto", "posterior_a_dispositiva", "voto_salvado", "nota", "estructura_no_confiable")
_PIDE_SALVAR = ("salva el voto", "salvan el voto", "salvamos el voto", "salvo el voto", "pone nota", "consigna nota")
_TILDES = {"a": "aáàäâ", "e": "eéèëê", "i": "iíìïî", "o": "oóòöô", "u": "uúùüû", "n": "nñ"}
_NO_CANDIDATAS = ("voto_salvado", "nota", "posterior_a_dispositiva")
_CON_BONO = ("considerando_sin_clasificar", "veredicto")
# Encabezados de disidencia por FORMA, con mayúscula inicial y en cualquier posición. La mención en minúscula
# dentro de una oración («Por mayoría (con el voto salvado de la magistrada Vargas González) se declara…», sen-1-0006-1371379
# 40642) NO es marca: en una muestra, las 21 apariciones con «V» mayúscula son encabezados y las 19 con minúscula, menciones.
_MARCA_FORMA = re.compile(
    r"Voto\s+(?:parcialmente\s+|particular\s+)?[Ss]alvado\s+(?:del|de\s+la|de\s+los|de\s+las)\s+[Mm]agistrad"
    r"|VOTO\s+(?:PARCIALMENTE\s+|PARTICULAR\s+)?SALVADO"
    r"|Nota\s+(?:del|de\s+la|de\s+los|de\s+las)\s+[Mm]agistrad|NOTA\s+(?:DEL|DE\s+LA|DE\s+LOS|DE\s+LAS)\s+MAGISTRAD")
# Solo DESPUÉS del «por tanto» propio, y sin punto entre «voto» y la mayúscula: «…salva el voto Con sumo respeto me separo…»
# (sen-1-1258-1316407 36598). El anuncio de la propia dispositiva («…salva el voto. Notifíquese.»: sen-1-1258-1283039 41268)
# no es marca.
_SALVA_SIN_PUNTO = re.compile(r"\b(?:El|La)\s+[Mm]agistrad[oa]\s+(?:(?:[A-ZÁÉÍÓÚÑ][\wáéíóúñü]+|de|del|la|y)\s+){1,6}"
                              r"salvan?\s+el\s+voto\s+(?=[A-ZÁÉÍÓÚÑ])")


def enlace(id_documento: str) -> str:
    """URL oficial para un documento (formato verificado renderizando, con control negativo)."""
    return URL_FALLO_OFICIAL + id_documento


@dataclass
class Mapa:
    """Dónde cae cada sección en un texto ya normalizado."""
    i_pt: int = -1
    fin_pt: int = -1
    ini_res: int = -1
    fin_res: int = -1
    ini_cons: int = -1
    marcas: list = field(default_factory=list)  # [(posición, 'voto_salvado' | 'nota')] ordenadas
    clasif: Clasificacion = field(default_factory=Clasificacion)
    _inicios: list = field(default_factory=list)

    @property
    def estructura(self) -> str:
        return self.clasif.estructura


def _tipo_marca(texto: str, pos: int) -> str:
    """'nota' si la marca de disidencia en `pos` es una nota o razones adicionales; si no, 'voto_salvado'."""
    corto = texto[pos:pos + 45].lower().lstrip()
    corto = re.sub(r"^(?:[ivxlc]+|\d+)?\s*[.\-–)]*\s*", "", corto)
    return "nota" if corto.startswith(("nota", "razones")) else "voto_salvado"


def marcas_por_forma(texto: str, i_pt: int) -> list[int]:
    """Posiciones de las marcas de disidencia que `extracto._marcas_disidencia` no reconoce."""
    salida = [m.start() for m in _MARCA_FORMA.finditer(texto)]
    if i_pt >= 0:
        salida += [m.start() for m in _SALVA_SIN_PUNTO.finditer(texto, i_pt + 1)]
    return salida


def mapa_secciones(texto: str, despacho: str | None = None) -> Mapa:
    """Mapa de secciones de un texto ya normalizado: dispositiva, disidencias, resultando y tramos del fondo."""
    i_pt, disp = por_tanto(texto)
    m = Mapa(i_pt=i_pt, fin_pt=i_pt + len(disp) if i_pt >= 0 else -1)
    posiciones = sorted(set(_marcas_disidencia(texto)) | set(marcas_por_forma(texto, i_pt)))
    m.marcas = [(p, _tipo_marca(texto, p)) for p in posiciones]
    r = _RESULTANDO.search(texto)
    c = _CONSIDERANDO.search(texto, r.end() if r else 0)
    if r and c:
        m.ini_res, m.fin_res = r.start(), c.start()
    if c and not (0 <= i_pt <= c.start()):  # un «considerando» después de la dispositiva no abre los considerandos
        m.ini_cons = c.start()
    m.clasif = clasificar(texto, despacho, i_pt, m.ini_cons)
    m._inicios = [a for a, _, _ in m.clasif.tramos]
    return m


def _disidencia(mapa: Mapa, pos: int) -> str | None:
    """Una disidencia corre desde su marca hasta el final, salvo que la dispositiva de mayoría venga DESPUÉS de ella
    (Constitucional: «III.- VOTO SALVADO… » y luego el POR TANTO final): ahí la disidencia termina en la dispositiva."""
    previas = [x for x in mapa.marcas if x[0] <= pos]
    if previas:
        marca, tipo = previas[-1]
        if not (0 <= mapa.i_pt and marca < mapa.i_pt <= pos):
            return tipo
    return None


def seccion_en(mapa: Mapa, pos: int) -> str:
    """Sección del fallo en `pos`, en este orden: estructura no confiable (salvo disidencias) > «por tanto» >
    disidencias > resultando > tramos del fondo > encabezado del fallo > posterior a la dispositiva > sin clasificar."""
    disidencia = _disidencia(mapa, pos)
    if mapa.estructura == "no_confiable":
        return disidencia or "estructura_no_confiable"
    if mapa.i_pt >= 0 and mapa.i_pt <= pos < mapa.fin_pt:
        return "por_tanto"
    if disidencia:
        return disidencia
    if mapa.ini_res <= pos < mapa.fin_res:
        return "resultando"
    k = bisect.bisect_right(mapa._inicios, pos) - 1
    if k >= 0 and pos < mapa.clasif.tramos[k][1]:
        return mapa.clasif.tramos[k][2]
    if 0 <= pos < mapa.ini_cons:
        return "encabezado_del_fallo"
    if mapa.fin_pt >= 0 and pos >= mapa.fin_pt:
        return "posterior_a_dispositiva"
    return "considerando_sin_clasificar"


def hay_disidencia(texto: str, mapa: Mapa) -> bool:
    """¿El fallo trae voto salvado o nota? Marcas de encabezado, o la dispositiva dice que alguien salva el voto o pone nota."""
    if mapa.marcas:
        return True
    if mapa.i_pt < 0:
        return False
    cola = texto[mapa.i_pt:mapa.i_pt + LARGO_POR_TANTO + 400].lower()
    return any(k in cola for k in _PIDE_SALVAR) or any(k in cola for k in _CORTES_DISPOSITIVA[2:6])


def aviso_dispositiva(clasif: Clasificacion) -> str | None:
    """Aviso cuando la guarda marca el fallo: dice lo medido y que la dispositiva mostrada puede no ser la de este
    voto. Se muestra la que elige `extracto.por_tanto`
    en vez de null: en los datos, los encabezados anteriores suelen ser resoluciones transcritas (la del juzgado, un precedente);
    el caso contrario existe (14915-2025: la sentencia anulada pegada después) y por eso el aviso no se quita."""
    if clasif.estructura != "no_confiable":
        return None
    if clasif.motivo_guarda == "encabezados":
        # «encontró»: los otros encabezados son casi siempre dispositivas transcritas, pero en 11 de 40 eran el título «VOTO
        # SALVADO … RESPECTO A LA PARTE DISPOSITIVA» o un «por tanto» en prosa (medido en una muestra): no afirmar que el fallo
        # tenga N dispositivas.
        return (f"el conector encontró {clasif.encabezados_dispositiva} encabezados de dispositiva en el fallo (los demás suelen ser "
                "resoluciones transcritas o el título de un voto salvado); se muestra el que toma por el de este voto, que "
                f"{MEDIDA_GUARDA}, pero puede ser el de otra resolución: abrí el enlace y verificalo en el fallo antes de citarlo")
    return ("el fallo trae otra resolución a continuación de la dispositiva; se muestra la dispositiva que la precede, pero puede no "
            "ser la de este voto: abrí el enlace y verificala en el fallo antes de citarla")


_COLA_DE_FIRMAS = re.compile(r"\s+(?:El|La|Los|Las)\s+(?:[Mm]agistrad|[Jj]ue[zc])\w*\b[^.]*$")


def sin_cola_de_firmas(disp: str) -> str:
    """Quita de la dispositiva la oración final cortada que anuncia un salvamento («… recurso. El magistrado Rueda Leal da»):
    `extracto.py` corta en «razones diferentes» y deja ese resto huérfano. Si no hay punto antes, no toca nada."""
    return _COLA_DE_FIRMAS.sub("", disp) if "." in disp else disp


def recortar(txt: str, n: int) -> str:
    """Espacios colapsados y corte en límite de palabra a lo sumo en `n` caracteres, con «…» si recortó."""
    txt = re.sub(r"\s+", " ", txt).strip()
    if len(txt) <= n:
        return txt
    corte = txt.rfind(" ", 0, n - 1)
    return txt[:corte if corte > n // 2 else n - 1].rstrip(" ,;:") + "…"


def recortar_dispositiva(txt: str, n: int) -> tuple[str, bool]:
    """(dispositiva recortada, ¿se recortó?). Corta al final de la última oración que entra, no a media oración.
    Cortada a media oración, «La magistrada Garro Vargas salva parcialmente el voto y ordena la
    condenatoria…», Claude completó lo que faltaba con lo del magistrado anterior y le atribuyó la condena en costas que el fallo
    le niega («pero no en costas»). Si ninguna oración entra entera, se corta por palabra como `recortar`."""
    limpio = re.sub(r"\s+", " ", txt).strip()
    if len(limpio) <= n:
        return limpio, False
    fin = max((m.end() for m in re.finditer(r"[.;:](?=\s)", limpio[:n - 1])), default=-1)
    if fin > n // 3:
        return limpio[:fin] + " […]", True
    return recortar(limpio, n), True


def _bordes(mapa: Mapa) -> list[int]:
    fijos = (mapa.i_pt, mapa.fin_pt, mapa.ini_res, mapa.fin_res, mapa.ini_cons, *(p for p, _ in mapa.marcas))
    return [*fijos, *(x for a, b, _ in mapa.clasif.tramos for x in (a, b))]


def _limite(mapa: Mapa, pos: int, fin: int) -> int:
    """Primer borde de sección posterior a `pos` (o `fin`): una ventana no cruza de un rótulo a otro."""
    return min((b for b in _bordes(mapa) if b > pos), default=fin)


def _ventana(texto: str, ini: int, tope: int, ancho: int = MAX_FRAGMENTO - 2) -> str:
    """Ventana que arranca cerca de `ini` y no pasa de `tope`, sin partir palabras, con «…» a los lados que corte."""
    ini = max(0, min(ini, len(texto)))
    if ini > 0 and not texto[ini - 1].isspace():
        sig = re.search(r"\s", texto[ini:ini + 40])
        ini = ini + sig.end() if sig else ini
    crudo = texto[ini:min(ini + ancho + 40, max(tope, ini + 1))]
    comp = re.sub(r"\s+", " ", crudo).strip()
    fin_corto = ini + len(crudo) < len(texto) or len(comp) > ancho
    if len(comp) > ancho:
        corte = comp.rfind(" ", 0, ancho)
        comp = comp[:corte if corte > ancho // 2 else ancho]
    return ("…" if ini > 0 else "") + comp.rstrip(" ,;:") + ("…" if fin_corto else "")


def _patron(termino: str) -> re.Pattern:
    """Regex de un término tal como lo ve el índice (sin tildes, sin caja): `prescripcion` encuentra «prescripción»."""
    plano = "".join(c for c in unicodedata.normalize("NFD", termino.lower()) if unicodedata.category(c) != "Mn")
    clases = "".join(f"[{_TILDES[c]}]" if c in _TILDES else re.escape(c) for c in plano)
    return re.compile(r"(?<!\w)" + clases + r"(?!\w)", re.I)


def _coincidencias(texto: str, terminos) -> list[tuple[int, int]]:
    """[(posición, índice de término)] ordenadas; hasta 400 por término (un fallo enorme no frena la respuesta)."""
    salida = []
    for k, t in enumerate(terminos):
        for n, m in enumerate(_patron(t).finditer(texto)):
            if n >= 400:
                break
            salida.append((m.start(), k))
    return sorted(salida)


def _mejor_ventana(coinc, mapa, lejos_de=None) -> int | None:
    """Posición cuyo entorno de 600 caracteres junta más términos distintos, fuera de disidencias y de lo posterior a la
    dispositiva. Lo sin clasificar y el veredicto pesan más (llevan un bono en el puntaje)."""
    posiciones = [p for p, _ in coinc]
    mejor, nota = None, 0
    for p, _ in coinc:
        sec = seccion_en(mapa, p)
        if sec in _NO_CANDIDATAS:
            continue
        if lejos_de is not None and abs(p - lejos_de) < MAX_FRAGMENTO:
            continue
        a, b = bisect.bisect_left(posiciones, p - 150), bisect.bisect_right(posiciones, p + 450)
        puntaje = len({k for _, k in coinc[a:b]}) + (0.5 if sec in _CON_BONO else 0)
        if puntaje > nota:
            mejor, nota = p, puntaje
    return mejor


def _fragmento_veredicto(t: str, mapa: Mapa) -> dict:
    """Arranca en el primer veredicto del fallo y CRUZA el borde del tramo hacia lo que sigue, salvo que lo que sigue
    sea otro rótulo; se devuelve `considerando_sin_clasificar` (lo que sigue suele ser el alegato vuelto a contar)."""
    pv = mapa.clasif.primer_veredicto
    fin_v = next(b for a, b, _ in mapa.clasif.tramos if a == pv)
    tope = fin_v if seccion_en(mapa, min(fin_v, len(t) - 1)) != "considerando_sin_clasificar" else _limite(mapa, fin_v, len(t))
    return {"texto": _ventana(t, pv, tope), "seccion": "considerando_sin_clasificar", "abre_con_veredicto": True}


def armar(texto: str, terminos=(), via: str = "literal", despacho: str | None = None) -> dict:
    """Fragmentos de un resultado: `{fragmentos: [{texto, seccion, abre_con_veredicto}], por_tanto, dispositiva_localizada,
    por_tanto_aviso, tipo_resolucion, hay_disidencia}`. `texto` es el guardado.

    Con términos que aparecen en el fallo: la ventana con más términos distintos y una segunda separada. Sin ellos: el objeto
    del recurso y el arranque del fondo, según `extracto.extraer`. Vía semántica con veredicto: el primer veredicto y el objeto.
    """
    t = normalizar(texto)
    mapa = mapa_secciones(t, despacho)
    coinc = _coincidencias(t, terminos) if terminos else []
    marcos: list[int] = []
    primero = _mejor_ventana(coinc, mapa) if coinc else None
    if primero is not None:
        marcos.append(max(0, primero - 150))
        otro = _mejor_ventana(coinc, mapa, lejos_de=primero)
        if otro is not None:
            marcos.append(max(0, otro - 150))
    ext = extraer(t)
    for parte in (ext.objeto, ext.fondo):
        if len(marcos) >= 2 or not parte:
            continue
        pos = t.find(parte[:60])
        if pos >= 0 and all(abs(pos - x) >= MAX_FRAGMENTO for x in marcos):
            marcos.append(pos)
    pos_objeto = t.find(ext.objeto[:60]) if ext.objeto else -1
    if via == "semantica":  # la semántica ordena por el sentido del objeto: el objeto va primero
        marcos.sort(key=lambda x: (x != pos_objeto if ext.objeto else 0, x))
    frags = []
    pv = mapa.clasif.primer_veredicto
    if via == "semantica" and pv is not None:
        frags.append(_fragmento_veredicto(t, mapa))
        resto = ([pos_objeto] if pos_objeto >= 0 else []) + marcos
        marcos = [x for x in resto if abs(x - pv) >= MAX_FRAGMENTO][:1]
    frags += [{"texto": _ventana(t, x, _limite(mapa, x, len(t))), "seccion": seccion_en(mapa, min(x, len(t) - 1)),
               "abre_con_veredicto": False} for x in marcos[:2 - len(frags)]]
    pt, pt_recortado = recortar_dispositiva(sin_cola_de_firmas(ext.por_tanto), MAX_POR_TANTO)  # también si no_confiable
    localizada = mapa.i_pt >= 0
    return {"fragmentos": [f for f in frags if f["texto"]], "por_tanto": pt, "por_tanto_recortado": pt_recortado,
            "dispositiva_localizada": localizada,
            "por_tanto_aviso": aviso_dispositiva(mapa.clasif), "tipo_resolucion": mapa.clasif.tipo_resolucion,
            "hay_disidencia": hay_disidencia(t, mapa)}
