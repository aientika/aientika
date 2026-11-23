"""`verificar_cita`: ¿esta frase está literal en el fallo, y dónde? Solo veredicto, nunca el texto de alrededor.

UBICA la frase: comprueba sobre el texto de la base que la frase exista literal (tras normalizar espacios y
comillas) y si cae antes de la dispositiva o dentro de un voto salvado o nota, y dice en qué sección del fallo cae. Ubica TODAS las
apariciones y juzga por la que manda (orden de prioridad: «por tanto» > veredicto > considerando sin clasificar > …). Desde la
1.3.0 NUNCA afirma que una frase sea criterio de la Sala: `citable_como_criterio` vale `no` o `indeterminado`, jamás `si`. Separar
el criterio del tribunal del alegato de parte o de una transcripción sigue siendo tarea de quien cita: tiene que leer el fallo.
"""

from __future__ import annotations

import re

from src.conector.fragmentos import enlace, mapa_secciones, seccion_en
from src.conector.ficha import DocumentoNoEncontrado
from src.indice.extracto import normalizar

MIN_FRASE = 15
MAX_FRASE = 2000
MAX_OCURRENCIAS = 50
_PRIORIDAD = ("por_tanto", "veredicto", "considerando_sin_clasificar", "estructura_no_confiable", "encabezado_del_fallo",
              "posterior_a_dispositiva", "antecedente", "alegato", "resultando", "nota", "voto_salvado")
_VEREDICTOS = {
    "por_tanto": "LITERAL_EN_DISPOSITIVA: la frase está en el «por tanto» de mayoría",
    "veredicto": ("LITERAL_EN_VEREDICTO: tiene la forma de la oración con que la Sala resuelve un motivo; en una resolución de "
                  "admisibilidad significa que pasa o no pasa a estudio; leé el fallo antes de citarla"),
    "considerando_sin_clasificar": ("LITERAL_EN_CONSIDERANDO_SIN_CLASIFICAR: está en los considerandos, antes de la dispositiva; "
                                    "el conector no determina si es razonamiento de la Sala, alegato de parte o transcripción: "
                                    "leé el fallo antes de citarla como criterio"),
    "estructura_no_confiable": ("LITERAL_ESTRUCTURA_NO_CONFIABLE: el fallo tiene más de una dispositiva o una resolución a "
                                "continuación de otra, y el conector no ubica sus partes: leé el fallo"),
    "encabezado_del_fallo": "LITERAL_EN_ENCABEZADO: está antes de los considerandos: encabezado, partes o trámite; leé el fallo",
    "posterior_a_dispositiva": ("LITERAL_DESPUES_DE_DISPOSITIVA: firmas, resto de la dispositiva, o un voto salvado o nota que el "
                                "conector no identificó: leé el fallo"),
    "antecedente": ("LITERAL_EN_ANTECEDENTE: objeto del recurso, antecedentes o hechos; no es razonamiento jurídico de la Sala "
                    "(los hechos probados sí los fija la Sala)"),
    "alegato": ("LITERAL_EN_ALEGATO: transcripción o síntesis de lo que alegó una parte; no es criterio de la Sala (se puede citar "
                "como alegato)"),
    "resultando": "LITERAL_EN_RESULTANDO: antecedentes o alegatos de las partes; no es criterio del tribunal",
    "nota": "LITERAL_SOLO_EN_NOTA: nota separada o razones adicionales; no es criterio de la mayoría",
    "voto_salvado": "LITERAL_SOLO_EN_VOTO_SALVADO: no es criterio de la mayoría",
}
# `no` donde el rótulo dice que no es criterio; `indeterminado` en todo lo demás. `si` no existe.
CITABLE = {"encabezado_del_fallo": "indeterminado", "resultando": "no", "considerando_sin_clasificar": "indeterminado",
           "antecedente": "no", "alegato": "no", "veredicto": "indeterminado", "por_tanto": "indeterminado",
           "posterior_a_dispositiva": "indeterminado", "voto_salvado": "no", "nota": "no", "estructura_no_confiable": "indeterminado"}
_NO_CRITERIO = ("alegato", "antecedente", "resultando")
_AVISO_REPETIDA = " — puede ser la Sala repitiendo o transcribiendo lo que alegó la parte"


def _patron_flexible(frase: str, ignorar_caja: bool = False) -> re.Pattern:
    """Regex de la frase con cualquier tramo de espacios (saltos de línea incluidos) equivalente a un espacio."""
    palabras = normalizar(frase).split()
    return re.compile(r"\s+".join(re.escape(p) for p in palabras), re.I if ignorar_caja else 0)


def evaluar(texto: str, frase: str, despacho: str | None = None) -> dict:
    """Veredicto de `frase` sobre un texto guardado (sin acceso a BD). Levanta ValueError si la frase es muy corta o muy larga."""
    frase = " ".join(normalizar(frase).split())
    if len(frase) < MIN_FRASE:
        raise ValueError(f"la frase tiene {len(frase)} caracteres; con menos de {MIN_FRASE} casi todo «aparece» y nada se prueba")
    if len(frase) > MAX_FRASE:
        raise ValueError(f"la frase pasa de {MAX_FRASE} caracteres: se verifica de a una cita")
    t = normalizar(texto)
    mapa = mapa_secciones(t, despacho)
    confiable = mapa.estructura == "confiable"
    localizada = mapa.i_pt >= 0  # 1.4.0: también si no_confiable (se muestra con aviso), pero sin ubicar la frase frente a ella
    pos = [m.start() for _, m in zip(range(MAX_OCURRENCIAS), _patron_flexible(frase).finditer(t))]
    if not pos:
        otra_caja = _patron_flexible(frase, True).search(t) is not None
        return {"literal": False, "veredicto": "NO_LITERAL: la frase no aparece tal cual en el fallo"
                + ("; existe con otras mayúsculas o minúsculas" if otra_caja else ""),
                "literal_ignorando_mayusculas": otra_caja, "ocurrencias": 0, "seccion": None, "secciones": [],
                "antes_de_dispositiva": None, "en_voto_salvado": False, "en_nota": False, "citable_como_criterio": None,
                "tambien_en_parte_no_criterio": False, "estructura": mapa.estructura, "dispositiva_localizada": localizada}
    secciones = [seccion_en(mapa, p) for p in pos]
    mejor = next(s for s in _PRIORIDAD if s in secciones)
    i_mejor = secciones.index(mejor)
    distintas = [s for s in _PRIORIDAD if s in secciones]
    otras = [s for s in distintas if s != mejor]
    repetida = any(s in _NO_CRITERIO for s in otras)
    veredicto = _VEREDICTOS[mejor]
    if otras:
        veredicto += f" (también aparece en: {', '.join(otras)})" + (_AVISO_REPETIDA if repetida else "")
    return {"literal": True, "veredicto": veredicto, "ocurrencias": len(pos), "seccion": mejor, "secciones": distintas,
            "antes_de_dispositiva": (pos[i_mejor] < mapa.i_pt) if localizada and confiable else None,
            "en_voto_salvado": "voto_salvado" in secciones, "en_nota": "nota" in secciones,
            "dispositiva_localizada": localizada, "citable_como_criterio": CITABLE[mejor],
            "tambien_en_parte_no_criterio": repetida, "estructura": mapa.estructura}


def verificar_cita(conn, id_documento: str, frase: str) -> dict:
    """Veredicto de `frase` contra el fallo `id_documento` de la base. DocumentoNoEncontrado si el id no existe; error de BD sube."""
    cur = conn.cursor()
    cur.execute("SELECT texto, despacho FROM documentos WHERE id_documento = %s", (id_documento,))
    fila = cur.fetchone()
    if not fila:
        raise DocumentoNoEncontrado(id_documento)
    return {"id": id_documento, **evaluar(fila[0], frase, fila[1] if len(fila) > 1 else None), "enlace": enlace(id_documento)}
