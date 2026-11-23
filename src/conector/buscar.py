"""`buscar`: núcleo de búsqueda del conector, sin MCP, sin OAuth y sin límites (eso es de otras capas).

Dos vías sobre la base: la semántica (`voyage-4`, distancia coseno exacta sobre `vectores`, sin índice aproximado) y la
literal (`websearch_to_tsquery` con la config `replica_simple`, AND de términos que se va aflojando). Donde hay vectores,
ambas se funden con RRF; los (despacho, año) SIN vectores salen en `solo_literal`, otra sección, para que un fallo sin vector
no compita en una lista que no lo puede ver. Hasta 10 resultados. Un error de BD o de Voyage sube como excepción: un
cero por falla nunca se presenta como «no hay jurisprudencia». El texto de la consulta no se registra aquí.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date

from src.conector.cobertura import cobertura
from src.conector import pertinencia as PT
from src.conector.ficha import identificacion
from src.conector.fragmentos import armar, enlace
from src.conector.voyage_consulta import MAX_CARACTERES
from src.indice.extracto import normalizar

MODELO = "voyage-4"
DIMENSION = 1024
MAX_RESULTADOS = 10
RESERVA_SOLO_LITERAL = 4  # lugares que se guardan para `solo_literal` si hay con qué llenarlos
CANDIDATOS_SEMANTICOS = 30
CANDIDATOS_LITERALES = 30
CANDIDATOS_FRASE = 400  # tope de la preselección cuando hay que confirmar una frase sobre el texto
TOPE_TERMINOS = 8
TOPE_FRASES = 3  # frases entrecomilladas por consulta: cada una es una regex sobre hasta CANDIDATOS_FRASE textos
_FECHA = re.compile(r"\d{4}-\d{2}-\d{2}")
MINIMO_LITERAL = 3  # con menos aciertos se afloja el AND quitando términos
RRF_K = 60
TIEMPO_MAXIMO = "25s"
_NIVELES = (8, 5, 3, 2)  # cada nivel es una consulta a la base (~0,4 s): pocos escalones
_PARADA = frozenset(
    "a al algo algun alguna algunas alguno algunos ante antes aquel aquella aun aunque bajo cada como con contra cual cuales "
    "cuando cuanto de del desde donde dos durante el ella ellas ello ellos en entre era es esa esas ese eso esos esta estaba "
    "estan este esto estos fue fueron ha han hasta hay la las le les lo los mas me mi mis muy ni no nos nuestro o otra otras "
    "otro otros para pero por porque que quien quienes se sea segun ser si sin sino sobre su sus tal tambien tanto te tiene "
    "tienen todo todos tras tu tus un una unas uno unos y ya cuales cuya cuyo debe deben puede pueden hace hacer diferencia "
    "existe existen respecto".split())


def _plano(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")


def terminos(consulta: str) -> list[str]:
    """Palabras útiles de la consulta (sin vacías ni cortas), sin repetir; lo entrecomillado cuenta como lo dicho."""
    vistos, salida = set(), []
    for w in re.findall(r"[\wáéíóúüñÁÉÍÓÚÜÑ]+(?:[-/.][\wáéíóúüñÁÉÍÓÚÜÑ]+)*", consulta):
        p = _plano(w)
        if (len(p) >= 3 or p.isdigit()) and p not in _PARADA and p not in vistos:
            vistos.add(p)
            salida.append(w.lower())
    return salida


def _consultas_literales(consulta: str) -> list[tuple[str, list[str], list[str], bool]]:
    """[(texto de la consulta, términos, frases, ¿con operadores?)] de lo más estricto a lo más flojo.

    Lo entrecomillado es una FRASE: el índice no guarda posiciones (`strip`), así que `websearch_to_tsquery` no puede buscar
    frases; se preselecciona con el AND de sus términos y la frase se confirma sobre el texto. Con `or` o `-x`
    sin comillas, la consulta va tal cual a `websearch_to_tsquery`. Lo demás va por `plainto_tsquery`: un AND puro. Con
    `websearch_to_tsquery`, «10-12-13» se vuelve una frase (`<->`) que NUNCA calza en un índice sin posiciones, y el parser
    parte esa palabra en '10', '-12', '-13' (comprobado con un caso positivo).
    """
    ts = terminos(consulta)
    if not ts:
        raise ValueError("la consulta no tiene términos útiles para buscar")
    frases = [" ".join(f.split()) for f in re.findall(r'"([^"]+)"', consulta) if f.strip()]
    if len(frases) > TOPE_FRASES:
        raise ValueError(f"la consulta trae {len(frases)} frases entre comillas; el máximo es {TOPE_FRASES}")
    if frases:
        return [(" ".join(ts), ts, frases, False)]
    if re.search(r"\s-\w|\bor\b", consulta):
        return [(consulta, ts, [], True)]
    niveles, vistos = [], set()
    for k in _NIVELES:
        k = min(k, len(ts), TOPE_TERMINOS)
        if k in vistos:
            continue
        vistos.add(k)
        por_largo = sorted(range(len(ts)), key=lambda i: (-len(ts[i]), i))[:k]  # lo largo es lo más específico
        elegidos = [ts[i] for i in sorted(por_largo)]
        niveles.append((" ".join(elegidos), elegidos, [], False))
    return niveles


def validar_entrada(consulta: str, desde=None, hasta=None) -> None:
    """Reglas de la entrada de `buscar`, TODAS antes de gastar nada (Voyage incluido): levanta ValueError con el motivo en palabras.

    Es la única fuente de estas reglas: `buscar` la llama de nuevo y la capa de herramientas la llama antes de embeber
    (una consulta sin términos útiles gastaba una llamada de embeddings y devolvía la unidad).
    """
    if not consulta or not consulta.strip():
        raise ValueError("consulta vacía")
    if len(" ".join(consulta.split())) > MAX_CARACTERES:
        raise ValueError(f"la consulta pasa de {MAX_CARACTERES} caracteres")
    for fecha in (desde, hasta):
        if fecha:
            try:
                if not _FECHA.fullmatch(str(fecha)):
                    raise ValueError
                date.fromisoformat(str(fecha))
            except ValueError:
                raise ValueError("las fechas van como AAAA-MM-DD") from None
    _consultas_literales(consulta)  # sin términos útiles o con demasiadas frases: ValueError


def _patron_frase(frase: str) -> str:
    """Regex POSIX de una frase: espacios flexibles, comillas intercambiables, caracteres especiales escapados."""
    def uno(c: str) -> str:
        if c in "\"'«»“”":
            return "[\"'«»“”]"
        return "\\" + c if c in "\\.^$|?*+()[]{}" else c
    return "[[:space:]]+".join("".join(uno(c) for c in w) for w in frase.split())


def _filtros(despacho, anno, desde, hasta) -> tuple[str, list]:
    """Fragmento SQL y parámetros de los filtros opcionales. La fecha sin dato se toma del primer día del mes cargado."""
    sql, p = "", []
    if despacho:
        limpio = despacho.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        sql += " AND unaccent(lower(d.despacho)) LIKE '%%' || unaccent(lower(%s)) || '%%'"
        p.append(limpio)
    if anno:
        sql += " AND d.anno = %s"
        p.append(int(anno))
    if desde:
        sql += " AND coalesce(d.fecha, make_date(d.anno, d.mes, 1)) >= %s"
        p.append(str(desde))
    if hasta:
        sql += " AND coalesce(d.fecha, make_date(d.anno, d.mes, 1)) <= %s"
        p.append(str(hasta))
    return sql, p


def _semantica(cur, vector, filtros: tuple[str, list]) -> list[tuple[str, float]]:
    """[(id, distancia coseno)] contra los vectores `voyage-4`, de la más cercana a la más lejana (exacto: sin índice aproximado).

    El orden de los parámetros cambió con la distancia en el SELECT: el vector va primero. Desempate por id: con extractos
    idénticos hay distancias iguales y el orden no debe variar entre corridas.
    """
    lit = "[" + ",".join(f"{x:.6g}" for x in vector) + "]"
    cur.execute("SELECT d.id_documento, v.vector <=> %s::halfvec AS dist FROM vectores v JOIN documentos d USING (id_documento) "
                "WHERE v.modelo = %s AND v.trozo = 0" + filtros[0] + " ORDER BY dist, d.id_documento LIMIT %s",
                (lit, MODELO, *filtros[1], CANDIDATOS_SEMANTICOS))
    return [(r[0], float(r[1])) for r in cur.fetchall()]


def _comparados(cur, filtros: tuple[str, list]) -> int:
    """Cuántos fallos con vector cubre el filtro (sin calcular distancias): el tamaño del grupo contra el que se buscó."""
    cur.execute("SELECT count(*) FROM vectores v JOIN documentos d USING (id_documento) WHERE v.modelo = %s AND v.trozo = 0"
                + filtros[0], (MODELO, *filtros[1]))
    return int(cur.fetchall()[0][0])


def _literal(cur, texto: str, pares: list[str], filtros: tuple[str, list], frases=(), operadores: bool = False) -> tuple[list[str], list[str], bool]:
    """(ids con vectores, ids sin vectores, ¿candidatos truncados?): las dos listas se rankean aparte, así una no tapa a la otra.

    Con frases se preselecciona por AND de términos (hasta CANDIDATOS_FRASE fallos) y se confirma la frase sobre el texto, sin
    tildes ni caja; si la preselección llenó el tope, la respuesta lo declara (puede haber más fallos con la frase).
    """
    pares = pares or [""]  # pg8000 no infiere el tipo de un arreglo vacío
    tope = f" LIMIT {CANDIDATOS_FRASE + 1}" if frases else ""
    origen = "c"
    if frases:
        origen = "c JOIN documentos t ON t.id_documento = c.id_documento" + " AND unaccent(t.texto) ~* unaccent(%s)" * len(frases)
    cur.execute(
        "WITH q AS (SELECT " + ("websearch_to_tsquery" if operadores else "plainto_tsquery") + "('replica_simple', %s) AS q),"
        " c AS (SELECT d.id_documento, d.despacho, d.anno, d.fecha, d.tsv FROM documentos d, q"
        "  WHERE d.tsv @@ q.q" + filtros[0] + tope + "),"
        " x AS (SELECT c.id_documento, (c.despacho || '|' || c.anno::text) = ANY(%s) AS con_vec,"
        "  row_number() OVER (PARTITION BY (c.despacho || '|' || c.anno::text) = ANY(%s)"
        "   ORDER BY ts_rank(c.tsv, (SELECT q FROM q)) DESC, c.fecha DESC NULLS LAST, c.id_documento) AS n FROM " + origen + ")"
        " SELECT x.id_documento, x.con_vec, " + ("(SELECT count(*) FROM c)" if frases else "0") +
        " FROM (SELECT 1) uno LEFT JOIN x ON x.n <= %s ORDER BY x.con_vec DESC NULLS LAST, x.n",
        (texto, *filtros[1], pares, pares, *[_patron_frase(f) for f in frases], CANDIDATOS_LITERALES))
    filas = cur.fetchall()
    truncado = bool(frases and filas and filas[0][2] > CANDIDATOS_FRASE)
    return [i for i, c, _ in filas if i and c], [i for i, c, _ in filas if i and not c], truncado


def _rrf(*listas: list[str]) -> list[tuple[str, int]]:
    """[(id, listas en que aparece)] por puntaje RRF descendente; el empate lo rompe el orden de la primera lista."""
    puntos: dict[str, float] = {}
    cuenta: dict[str, int] = {}
    for lista in listas:
        for rango, i in enumerate(lista, 1):
            puntos[i] = puntos.get(i, 0.0) + 1.0 / (RRF_K + rango)
            cuenta[i] = cuenta.get(i, 0) + 1
    return [(i, cuenta[i]) for i in sorted(puntos, key=lambda x: -puntos[x])]


def _terminos_de_fragmentos(terms: list[str]) -> list[str]:
    """Los TOPE_TERMINOS más largos (en su orden): `armar` recorre el fallo entero por término, y con `or` o comillas llegan cientos."""
    if len(terms) <= TOPE_TERMINOS:
        return terms
    largos = sorted(range(len(terms)), key=lambda i: (-len(terms[i]), i))[:TOPE_TERMINOS]
    return [terms[i] for i in sorted(largos)]


def _resultado(fila, via: str, terms: list[str], distancia: float | None = None) -> dict:
    """Un fallo de la respuesta. `distancia` solo en `semantica` y `ambas`: un literal no trae (ausencia ≠ cero)."""
    id_, despacho, tipo, numero, fecha, expediente, texto = fila
    terms = _terminos_de_fragmentos(terms)
    ident = identificacion(normalizar(texto), numero, fecha, expediente)
    extra = {"distancia": PT.distancia(distancia)} if via != "literal" else {}
    return {"id": id_, "numero": ident["numero"], "fecha": ident["fecha"], "despacho": despacho, "tipo": tipo,
            "expediente": ident["expediente"], "via": via, **extra,
            **armar(texto, terms, "semantica" if via != "literal" else "literal", despacho), "enlace": enlace(id_)}


def _aviso(hay: bool, truncado: bool, pertinencia: str | None = None) -> str | None:
    """Advertencia al modelo: un vacío no es inexistencia, y una frase con preselección truncada puede tener más fallos.

    Orden: la degradación la antepone `herramientas`; acá van truncado, pertinencia y vacío.
    """
    partes = []
    if truncado:
        partes.append(f"La preselección de la frase llegó al tope de {CANDIDATOS_FRASE} fallos: puede haber más fallos con esa "
                      "frase; agregá términos o filtros (despacho, año) para acotar.")
    if pertinencia:
        partes.append(pertinencia)
    if not hay:
        partes.append("Sin resultados en lo cargado. No prueba que no exista jurisprudencia: ver la cobertura.")
    return " ".join(partes) or None


def buscar(conn, consulta: str, despacho: str | None = None, anno: int | None = None, desde=None, hasta=None,
           vector_consulta: list[float] | None = None) -> dict:
    """Busca `consulta` en la base. `vector_consulta` es el embebido `voyage-4` (input_type=query) de la misma consulta;
    sin él solo corre la vía literal y la respuesta lo dice. Devuelve `{cobertura, resultados, solo_literal, …}`."""
    validar_entrada(consulta, desde, hasta)
    if vector_consulta is not None and len(vector_consulta) != DIMENSION:
        raise ValueError(f"vector de {len(vector_consulta)} dimensiones; {MODELO} usa {DIMENSION}")
    cob = cobertura(conn)
    filtros = _filtros(despacho, anno, desde, hasta)
    niveles = _consultas_literales(consulta)
    cur = conn.cursor()
    try:
        cur.execute(f"SET LOCAL statement_timeout = '{TIEMPO_MAXIMO}'")
        sem = _semantica(cur, vector_consulta, filtros) if vector_consulta is not None else []
        comparados = _comparados(cur, filtros) if vector_consulta is not None else 0
        usado, con_vec, sin_vec, truncado = niveles[-1], [], [], False
        for nivel in niveles:
            con_vec, sin_vec, truncado = _literal(cur, nivel[0], cob["pares_con_vectores"], filtros, nivel[2], nivel[3])
            usado = nivel
            if len(con_vec) + len(sin_vec) >= MINIMO_LITERAL:
                break
        ids_sem = [i for i, _ in sem]
        principal = _rrf(ids_sem, con_vec) if vector_consulta is not None else [(i, 1) for i in con_vec]
        n_sol = min(len(sin_vec), RESERVA_SOLO_LITERAL)
        ids = [i for i, _ in principal][:MAX_RESULTADOS - n_sol]
        sol = sin_vec[:MAX_RESULTADOS - len(ids)]
        cur.execute("SELECT id_documento, despacho, tipo, numero, fecha, expediente, texto FROM documentos "
                    "WHERE id_documento = ANY(%s)", (ids + sol,))
        filas = {f[0]: f for f in cur.fetchall()}
    finally:
        conn.rollback()
    faltan = [i for i in ids + sol if i not in filas]
    if faltan:
        raise RuntimeError(f"ids que la búsqueda devolvió y la base no tiene: {faltan[:3]}")
    cuenta, dist = dict(principal), dict(sem)
    resultados = [_resultado(filas[i], "ambas" if cuenta[i] > 1 else ("semantica" if i in dist else "literal"), usado[1], dist.get(i))
                  for i in ids]
    solo = [_resultado(filas[i], "literal", usado[1]) for i in sol]
    est = PT.estado(vector_consulta is not None, comparados)
    estricto = bool(usado[2]) or (not usado[3] and usado[1] == niveles[0][1])  # frase confirmada o todos los términos
    con_todos = sum(x["via"] != "semantica" for x in resultados + solo) if estricto else 0
    pert = PT.aviso(est, comparados, any(x["via"] != "literal" for x in resultados), con_todos)
    return {"cobertura": cob["linea"], "semantica_usada": vector_consulta is not None,
            "literal": {"terminos": usado[1], "frases": usado[2], "nivel": len(usado[1]), "candidatos_truncados": truncado},
            "senal_semantica": {"estado": est, "comparados": comparados},
            "distancia_corte": PT.distancia(sem[-1][1]) if sem else None,
            "total": len(resultados) + len(solo), "resultados": resultados, "solo_literal": solo,
            "aviso": _aviso(bool(resultados or solo), truncado, pert)}
