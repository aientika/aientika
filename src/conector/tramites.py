"""Trámites dentro del conector: búsqueda y ficha sobre el catálogo del MEIC.

Los datos viajan en la imagen (`datos/tramites_meic.json.gz`, versionado en el repo): no
tocan la base. La búsqueda es por palabras, sin tildes, con más peso al nombre del trámite que a la descripción y los requisitos, y a las palabras
raras del catálogo que a las comunes (IDF).
Toda salida lleva su FUENTE con enlace oficial y la advertencia de confirmar con la institución: el agente debe indicar la
fuente de lo que dice.
"""

from __future__ import annotations

import gzip
import json
import math
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

ARCHIVO = Path(__file__).resolve().parent / "datos" / "tramites_meic.json.gz"
MAX_RESULTADOS = 8
# Solo cuentan los trámites con al menos esta fracción del puntaje del mejor: así no entran trámites que coinciden solo
# en una palabra común, como «registro».
CORTE_RELATIVO = 0.5
AVISO = ("Dato del Catálogo Nacional de Trámites (MEIC). Confirmá requisitos, costo y plazo con la institución antes de presentar: "
         "la ficha puede no estar al día.")
_VACIAS = set("de del la las los el y o en para por con sin un una que como a al se su sus es mi me quiero necesito hacer tramite "
              "tramites requisitos requisito cual cuales donde sacar obtener solicitar pedir agentika aientika aiéntika".split())


class TramiteNoEncontrado(LookupError):
    """No hay un trámite con ese id en el catálogo cargado."""


class CatalogoNoDisponible(RuntimeError):
    """El archivo del catálogo no está en la imagen: es un error del servicio, no «cero trámites»."""


def _plano(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", (texto or "").lower()) if unicodedata.category(c) != "Mn")


def _raiz(p: str) -> str:
    # Singular = plural: «registro sanitario alimento» debe traer también la ficha cuyo nombre dice «… (Alimentos)».
    return p[:-1] if len(p) > 4 and p.endswith("s") else p


def _palabras(texto: str) -> list[str]:
    return [_raiz(p) for p in re.findall(r"[a-z0-9]+", _plano(texto)) if len(p) > 2 and p not in _VACIAS]


@lru_cache(maxsize=1)
def catalogo(archivo: Path = ARCHIVO) -> dict:
    """El catálogo cargado (una vez por proceso), con un índice de texto por trámite."""
    if not archivo.exists():
        raise CatalogoNoDisponible(str(archivo))
    with gzip.open(archivo, "rt", encoding="utf-8") as g:
        datos = json.load(g)
    for t in datos["tramites"]:
        t["_nombre"] = set(_palabras(t["nombre"]))
        t["_resto"] = set(_palabras(" ".join([t.get("descripcion") or "", t["institucion"], " ".join(t.get("requisitos", []))])))
        t["_inst"] = _plano(t["institucion"])
    datos["_por_id"] = {int(t["id"]): t for t in datos["tramites"]}
    # Peso por rareza (IDF): «divorcio» está en 2 fichas y pesa mucho; «registro», en cientos, pesa poco.
    df: dict[str, int] = {}
    for t in datos["tramites"]:
        for p in t["_nombre"] | t["_resto"]:
            df[p] = df.get(p, 0) + 1
    n = len(datos["tramites"])
    datos["_idf"] = {p: math.log((n + 1) / (c + 1)) + 1 for p, c in df.items()}
    return datos


def fuente(t: dict, actualizado: str) -> str:
    """La línea de fuente que el asistente tiene que transmitir."""
    return f"Fuente: Catálogo Nacional de Trámites (MEIC), ficha {t['id']}, consultada el {t.get('consultado') or actualizado}: {t['fuente']}"


def buscar(consulta: str, institucion: str | None = None, archivo: Path = ARCHIVO) -> dict:
    """Los trámites que mejor coinciden con `consulta` (y con `institucion`, si se da). Lista vacía = ninguna palabra coincidió."""
    datos = catalogo(archivo)
    palabras = set(_palabras(consulta))
    if not palabras:
        raise ValueError("La consulta no trae palabras para buscar: decí qué trámite o tema buscás.")
    inst = _plano(institucion) if institucion else None
    idf = datos["_idf"]
    peso_consulta = sum(idf.get(p, max(idf.values(), default=1)) for p in palabras)
    puntuados = []
    for t in datos["tramites"]:
        if inst and inst not in t["_inst"]:
            continue
        comunes = palabras & (t["_nombre"] | t["_resto"])
        # Cobertura al cuadrado: un trámite que coincide en una o dos palabras de la consulta («reconocimiento mutuo») no le gana al
        # que cubre la parte que más pesa («divorcio»).
        cobertura = sum(idf.get(p, 0) for p in comunes) / peso_consulta if peso_consulta else 0
        puntos = sum(idf[p] * (3 if p in t["_nombre"] else 1) for p in comunes) * cobertura ** 2
        if puntos:
            puntuados.append((puntos, t))
    if puntuados:
        mejor = max(p for p, _ in puntuados)
        puntuados = [x for x in puntuados if x[0] >= CORTE_RELATIVO * mejor]
    puntuados.sort(key=lambda x: (-round(x[0], 6), len(x[1]["_nombre"]), x[1]["nombre"]))  # empate: el nombre más enfocado
    resultados = [{"id": t["id"], "nombre": t["nombre"], "institucion": t["institucion"], "descripcion": (t.get("descripcion") or "")[:300],
                   "costo": t.get("costo") or t.get("tipo_costo"), "plazo": t.get("plazo"), "fuente": fuente(t, datos["actualizado"])}
                  for _, t in puntuados[:MAX_RESULTADOS]]
    salida = {"total": len(puntuados), "resultados": resultados, "aviso": AVISO,
              "cobertura": f"Catálogo Nacional de Trámites (MEIC): {len(datos['tramites'])} trámites, actualizado al {datos['actualizado']}."}
    if not resultados:
        salida["nota"] = ("Ninguna ficha usa esas palabras. No prueba que el trámite no exista: probá con otras palabras o con el nombre "
                          "de la institución.")
    return salida


def ficha(id_: int | str, archivo: Path = ARCHIVO) -> dict:
    """La ficha completa del trámite, con su fuente y la advertencia."""
    datos = catalogo(archivo)
    try:
        t = datos["_por_id"][int(id_)]
    except (KeyError, ValueError):
        raise TramiteNoEncontrado(str(id_)) from None
    salida = {k: v for k, v in t.items() if not k.startswith("_")}
    salida["fuente"] = fuente(t, datos["actualizado"])
    salida["enlace_oficial"] = t["fuente"]
    salida["aviso"] = AVISO
    return salida


def resumen(archivo: Path = ARCHIVO) -> dict:
    """Para `catalogo`: cuántos trámites, de cuántas instituciones y a qué fecha."""
    datos = catalogo(archivo)
    raices = {t["institucion"].split(" - ")[0] for t in datos["tramites"]}
    return {"tramites": len(datos["tramites"]), "instituciones": len(raices), "actualizado": datos["actualizado"]}
