"""Ficha de un fallo: encabezado tomado del propio texto, «por tanto» de mayoría, disidencias y enlace. Sin texto íntegro.

La fecha y la hora de una sentencia salen del encabezado del fallo, no de la memoria de trabajo ni del metadato. El
redactor sale SOLO de la línea «Redacta el/la Magistrado/a…» (el metadato del índice no es confiable); si no
está en el texto, se omite y se dice. La hora del encabezado viene en letras («las nueve horas treinta y tres minutos»).
Si el fallo tiene más de un encabezado de dispositiva u otra resolución pegada, `por_tanto` no se deja en null: se muestra la que elige
`extracto.por_tanto`, siempre con el aviso de que puede ser la de otra resolución; las secciones siguen sin rotular.
"""

from __future__ import annotations

import re

from src.conector.fragmentos import Mapa, aviso_dispositiva, enlace, hay_disidencia, mapa_secciones, recortar, recortar_dispositiva
from src.indice.extracto import normalizar, por_tanto

MAX_POR_TANTO_FICHA = 1500
_UNIDADES = {"cero": 0, "un": 1, "una": 1, "uno": 1, "primero": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7,
             "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12, "trece": 13, "catorce": 14, "quince": 15,
             "dieciseis": 16, "diecisiete": 17, "dieciocho": 18, "diecinueve": 19, "veinte": 20, "veintiun": 21,
             "veintiuno": 21, "veintiuna": 21, "veintidos": 22, "veintitres": 23, "veinticuatro": 24, "veinticinco": 25,
             "veintiseis": 26, "veintisiete": 27, "veintiocho": 28, "veintinueve": 29, "treinta": 30, "cuarenta": 40,
             "cincuenta": 50}
_MESES = {"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7, "agosto": 8, "setiembre": 9,
          "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12}
_PALABRA = r"[a-záéíóúñ]+"
_ENCABEZADO = re.compile(
    rf"a\s+las?\s+(?P<hora>{_PALABRA})\s+horas?(?:\s+(?:con\s+|y\s+)?(?P<min>{_PALABRA}(?:\s+y\s+{_PALABRA})?)\s+minutos?)?"
    rf"(?:\s+y\s+(?P<seg>{_PALABRA}(?:\s+y\s+{_PALABRA})?)\s+segundos?)?\s+del?\s+(?P<dia>{_PALABRA}(?:\s+y\s+{_PALABRA})?|\d{{1,2}})"
    rf"\s+de\s+(?P<mes>{_PALABRA})\s+(?:de\s+|del\s+)?(?P<anno>[a-záéíóúñ ]+?|\d{{4}})\s*[.,\-–]", re.I)
_RES = re.compile(r"\bRes(?:oluci[oó]n)?\b\s*[.:]?\s*(?:N[º°o]\.?\s*)?([0-9][\w\-]*)", re.I)
_EXP = re.compile(r"\bExp(?:ediente)?\s*[.:]\s*(\d{1,2}-\d{3,6}-\d{3,4}-[A-Z]{2,3})")
_REDACTA = re.compile(r"Redacta\s+(?:el|la)\s+(?:[Mm]agistrad[oa]|[Jj]uez[a]?)\s+((?:[A-ZÁÉÍÓÚÑ][a-záéíóúñü]+)"
                      r"(?:\s+(?:de\s+(?:la\s+)?|del\s+)?[A-ZÁÉÍÓÚÑ][a-záéíóúñü]+){0,3})")


class DocumentoNoEncontrado(LookupError):
    """El id no está en la base: se dice, nunca se devuelve una ficha vacía."""


def _plano(s: str) -> str:
    return s.lower().translate(str.maketrans("áéíóúü", "aeiouu"))


def numero_en_letras(frase: str) -> int | None:
    """Entero de una expresión en letras del 0 al 2999 («veintitrés», «treinta y tres», «dos mil veinticinco»); None si no se entiende."""
    palabras = [w for w in _plano(frase).split() if w != "y"]
    total, parcial = 0, 0
    for w in palabras:
        if w == "mil":
            total, parcial = total + max(parcial, 1) * 1000, 0
        elif w in _UNIDADES:
            parcial += _UNIDADES[w]
        else:
            return None
    return total + parcial if palabras else None


def encabezado(texto: str) -> dict:
    """{fecha, hora} del encabezado del fallo («a las nueve horas treinta y tres minutos del veinticinco de setiembre de…»)."""
    m = _ENCABEZADO.search(texto[:4000])
    if not m:
        return {"fecha": None, "hora": None}
    hora, minutos = numero_en_letras(m["hora"]), numero_en_letras(m["min"]) if m["min"] else 0
    dia = int(m["dia"]) if m["dia"].isdigit() else numero_en_letras(m["dia"])
    anno = int(m["anno"]) if m["anno"].strip().isdigit() else numero_en_letras(m["anno"])
    mes = _MESES.get(_plano(m["mes"]))
    fecha = f"{anno:04d}-{mes:02d}-{dia:02d}" if anno and mes and dia and 1 <= dia <= 31 else None
    ok = hora is not None and minutos is not None and 0 <= hora <= 23 and 0 <= minutos <= 59
    return {"fecha": fecha, "hora": f"{hora:02d}:{minutos:02d}" if ok else None}


def redactor(texto: str) -> str | None:
    """Nombre tras «Redacta el/la Magistrado/a…»; None si el texto no lo trae. Nunca el metadato."""
    m = _REDACTA.search(texto)
    return m.group(1).strip() if m else None


def disidencias(texto: str, mapa: Mapa | None = None) -> list[dict]:
    """[{tipo, encabezado}] de cada voto salvado o nota, con las primeras palabras de su encabezado (sin repetir la misma marca).
    Usa el mismo mapa que las secciones, incluidas formas como «Voto parcialmente salvado de…»."""
    mapa, salida, ultimo = mapa or mapa_secciones(texto), [], -100
    for pos, tipo in mapa.marcas:
        if pos - ultimo >= 40:  # dos reglas distintas de extracto.py suelen marcar el mismo encabezado
            salida.append({"tipo": tipo, "encabezado": recortar(texto[pos:pos + 110], 100)})
        ultimo = pos
    return salida


def identificacion(texto: str, numero, fecha, expediente) -> dict:
    """Número, fecha, hora y expediente tomados del encabezado del fallo (`texto` ya normalizado); el metadato solo de respaldo."""
    enc, res, exp = encabezado(texto), _RES.search(texto[:3000]), _EXP.search(texto[:3000])
    return {
        "numero": res.group(1) if res else numero, "numero_origen": "encabezado del fallo" if res else "metadato",
        "fecha": enc["fecha"] or (fecha.isoformat() if fecha else None),
        "fecha_origen": "encabezado del fallo" if enc["fecha"] else "metadato",
        "hora": enc["hora"],
        "fecha_metadato_difiere": bool(enc["fecha"] and fecha and enc["fecha"] != fecha.isoformat()),
        "expediente": exp.group(1) if exp else expediente,
    }


def ficha(conn, id_documento: str) -> dict:
    """Ficha del documento `id_documento`. Levanta DocumentoNoEncontrado si no existe; un error de BD sube tal cual."""
    cur = conn.cursor()
    cur.execute("SELECT id_documento, despacho, tipo, numero, numero_padre, fecha, expediente, texto "
                "FROM documentos WHERE id_documento = %s", (id_documento,))
    fila = cur.fetchone()
    if not fila:
        raise DocumentoNoEncontrado(id_documento)
    id_, despacho, tipo, numero, padre, fecha, expediente, bruto = fila
    texto = normalizar(bruto)
    mapa, nombre = mapa_secciones(texto, despacho), redactor(texto)
    pt, pt_recortado = (recortar_dispositiva(por_tanto(texto)[1], MAX_POR_TANTO_FICHA) if mapa.i_pt >= 0 else (None, False))
    return {
        "id": id_, "tipo": tipo, "despacho": despacho, **identificacion(texto, numero, fecha, expediente),
        "numero_padre": padre,
        "redactor": nombre,
        "redactor_nota": None if nombre else "no consta en el texto; el metadato del índice no sirve para citar",
        "por_tanto": pt, "por_tanto_recortado": pt_recortado,
        "dispositiva_localizada": mapa.i_pt >= 0, "por_tanto_aviso": aviso_dispositiva(mapa.clasif),
        "tipo_resolucion": mapa.clasif.tipo_resolucion, "estructura": mapa.estructura,
        "hay_disidencia": hay_disidencia(texto, mapa), "disidencias": disidencias(texto, mapa),
        "enlace": enlace(id_),
    }
