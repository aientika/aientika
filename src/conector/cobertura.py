"""Cobertura de la base, medida en la base y nunca escrita a mano: qué (despacho, año) llevan vectores `voyage-4` y cuáles
solo búsqueda literal, y hasta qué fecha llegan los datos. La línea que abre cada `buscar` sale de aquí.

Un año cuenta como «semántico» solo si sus vectores cubren (casi) todo lo embebible de ese año; si no, se declara parcial con su
porcentaje. Los documentos sin vector (EXT, rechazos formales, ejecuciones) siempre se encuentran solo por la vía literal.
"""

from __future__ import annotations

import datetime as dt
import time

from src.indice.alcance_vectores import ANNOS_TRIBUNALES_VALIDADOS, DESPACHOS_CON_VECTORES

MODELO = "voyage-4"
UMBRAL_COMPLETO = 0.99
VIGENCIA_S = 600
_CR = dt.timezone(dt.timedelta(hours=-6))
_cache: dict = {}


def _anos(lista) -> str:
    lista = sorted(lista)
    return ", ".join(str(a) for a in lista) if lista else "ninguno"


def medir(conn) -> dict:
    """Consulta la base y devuelve la cobertura estructurada. Un error de BD sube: jamás se devuelve una cobertura vacía."""
    cur = conn.cursor()
    cur.execute("SELECT d.despacho, d.anno, count(*) FROM vectores v JOIN documentos d USING (id_documento) "
                "WHERE v.modelo = %s AND v.trozo = 0 GROUP BY 1, 2", (MODELO,))
    con_vectores = {(r[0], r[1]): r[2] for r in cur.fetchall()}
    cur.execute("SELECT anno, count(*) FROM documentos GROUP BY 1 ORDER BY 1")
    por_anno = {r[0]: r[1] for r in cur.fetchall()}
    if not por_anno:
        raise RuntimeError("la base no tiene documentos: no hay cobertura que declarar")
    annos_vec = sorted({a for _, a in con_vectores})
    # Lo embebible por año y despacho, de TODOS los despachos: un tribunal de un año sin validar cuenta con 0 vectores. Medir solo
    # lo que el alcance deja embeber atribuiría a ese año una búsqueda por significado en tribunales que no la tienen.
    cur.execute("SELECT anno, despacho, count(*) FROM documentos WHERE tipo = 'SNT' AND clase_f2 = 'embeber' GROUP BY 1, 2")
    embebibles = {(r[0], r[1]): r[2] for r in cur.fetchall()}
    # `fecha > hoy` existe en los datos (un fallo de 2025 con fecha 2026-12-19): no se toma como «hasta cuándo llegan»
    cur.execute("SELECT max(cargado_en), max(fecha) FILTER (WHERE fecha <= current_date) FROM documentos")
    cargado, ultimo_fallo = cur.fetchone()
    anos = {}
    for a in annos_vec:
        n = sum(c for (_, x), c in con_vectores.items() if x == a)
        total = sum(c for (x, d), c in embebibles.items() if x == a and (d in DESPACHOS_CON_VECTORES or a in ANNOS_TRIBUNALES_VALIDADOS)) or n
        anos[a] = {"vectores": n, "embebibles": total, "fraccion": round(n / total, 4),
                   "tribunales": any(d not in DESPACHOS_CON_VECTORES for d, x in con_vectores if x == a)}
    por_grupo = {}
    for grupo, es in (("Salas", True), ("tribunales", False)):
        g = {}
        for a in sorted({x for x, d in embebibles if (d in DESPACHOS_CON_VECTORES) == es}):
            total = sum(c for (x, d), c in embebibles.items() if x == a and (d in DESPACHOS_CON_VECTORES) == es)
            n = sum(c for (d, x), c in con_vectores.items() if x == a and (d in DESPACHOS_CON_VECTORES) == es)
            g[a] = {"vectores": n, "embebibles": total, "fraccion": round(n / total, 4) if total else 0.0}
        por_grupo[grupo] = g
    return {"annos_cargados": sorted(por_anno), "documentos_por_anno": por_anno, "semantica": anos, "por_grupo": por_grupo,
            "pares_con_vectores": sorted(f"{d}|{a}" for d, a in con_vectores),
            "datos_cargados_al": cargado.astimezone(_CR).date().isoformat() if cargado else None,
            "fallos_hasta": ultimo_fallo.isoformat() if ultimo_fallo else None}


def linea(c: dict) -> str:
    """La línea de cobertura que abre cada respuesta de `buscar`, a partir de `medir`."""
    partes = []
    for grupo, etiqueta in (("Salas", "en las Salas"), ("tribunales", "en los tribunales")):
        g = c.get("por_grupo", {}).get(grupo, {})
        completos = [a for a, v in sorted(g.items()) if v["fraccion"] >= UMBRAL_COMPLETO]
        parciales = [f"{a} ({v['fraccion']:.0%})" for a, v in sorted(g.items()) if 0 < v["fraccion"] < UMBRAL_COMPLETO]
        literal = [a for a, v in sorted(g.items()) if v["vectores"] == 0]
        dichos = []
        if completos:
            dichos.append(f"en {_anos(completos)}")
        if parciales:
            dichos.append(f"en parte de {', '.join(parciales)}")
        if dichos:
            frase = ("búsqueda por significado (voyage-4) " if not partes else "") + f"{etiqueta} " + " y ".join(dichos)
            if literal:
                frase += f", y solo búsqueda literal en {_anos(literal)}"
            partes.append(frase)
        elif literal and any(p.startswith("búsqueda por significado") for p in partes):
            partes.append(f"{etiqueta}, solo búsqueda literal")
    solo_literal = [a for a in c["annos_cargados"] if a not in c["semantica"]]
    if solo_literal:
        partes.append(f"solo búsqueda literal en {_anos(solo_literal)}")
    if c["semantica"]:
        partes.append("lo que no lleva vector (resoluciones breves, rechazos formales) se encuentra solo por búsqueda literal")
    return (f"COBERTURA: {'; '.join(partes)}. Datos cargados al {c['datos_cargados_al']}. Un resultado vacío no prueba que no "
            f"exista jurisprudencia: la búsqueda es en la base de Aiéntika, en los años {_anos(c['annos_cargados'])}, no en "
            "toda la jurisprudencia publicada.")


def _es_sala(nombre: str) -> bool:
    return nombre.startswith("Sala ")


def despachos(conn, ahora=time.monotonic) -> list[dict]:
    """Por despacho: cuántas resoluciones hay, la fecha de la primera y la de la más reciente (para `catalogo`). Las Salas primero,
    después los tribunales por cantidad. Memoria de 10 minutos; un error de BD sube.
    """
    t = ahora()
    if _cache.get("d") and t - _cache["td"] < VIGENCIA_S:
        return _cache["d"]
    cur = conn.cursor()
    # Las fechas se toman solo de resoluciones cuya fecha cae en su propio año: unos 440 traen una fecha de
    # metadato imposible (el voto 08212-2023 de la Sala Constitucional con «1990-01-05») y con min(fecha) el catálogo decía «desde
    # 1990» de una base que empieza en 2022. Y, como en `medir`, una fecha futura no cuenta como «la más reciente».
    cur.execute("SELECT despacho, count(*), min(anno) FILTER (WHERE extract(year FROM fecha) = anno), "
                "max(anno) FILTER (WHERE extract(year FROM fecha) = anno), "
                "min(fecha) FILTER (WHERE extract(year FROM fecha) = anno), "
                "max(fecha) FILTER (WHERE extract(year FROM fecha) = anno AND fecha <= current_date) FROM documentos GROUP BY 1")
    filas = [{"despacho": d, "resoluciones": n, "annos": (f"{a1}-{a2}" if a1 != a2 else str(a1)) if a1 else "s. f.",
              "desde": a.isoformat() if a else None, "hasta": b.isoformat() if b else None}
             for d, n, a1, a2, a, b in cur.fetchall()]
    if not filas:
        raise RuntimeError("la base no tiene documentos: no hay despachos que declarar")
    filas.sort(key=lambda x: (not _es_sala(x["despacho"]), -x["resoluciones"], x["despacho"]))
    _cache.update(d=filas, td=t)
    return filas


def cobertura(conn, ahora=time.monotonic, refrescar: bool = False) -> dict:
    """`medir` con memoria de 10 minutos (son dos agregaciones sobre toda la base). `refrescar` fuerza una medición nueva."""
    t = ahora()
    if not refrescar and _cache.get("c") and t - _cache["t"] < VIGENCIA_S:
        return _cache["c"]
    c = medir(conn)
    c["linea"] = linea(c)
    _cache.update(c=c, t=t)
    return c
