"""Qué tan informativa es la vía por significado de una `buscar`.

Expone el dato sin interpretarlo: la distancia de cada resultado y cuántos fallos con vector había para comparar. NO etiqueta un
fallo como «cercano» ni «sobre el punto»: ninguna señal medida respalda esa etiqueta, y una etiqueta sin respaldo es peor que ninguna (una lista marcada «cercana» se lee como jurisprudencia
sobre el punto). Funciones puras: se prueban sin base.
"""

from __future__ import annotations

N_MINIMO = 50  # con menos fallos con vector en el filtro, la lista son «los más parecidos de un grupo chico»
DECIMALES = 3

SIN_VECTOR_DE_CONSULTA = "sin_vector_de_consulta"  # degradación: no hubo embebido de la consulta
FILTRO_SIN_VECTORES = "filtro_sin_vectores"  # cobertura: el filtro no tiene fallos con búsqueda por significado
GRUPO_CHICO = "grupo_chico"
SIN_EVALUAR = "sin_evaluar"  # hay grupo suficiente; la cercanía no se evalúa (no hay señal que la respalde)


def estado(hubo_vector: bool, comparados: int) -> str:
    """Estado de la vía por significado según haya vector de consulta y cuántos fallos con vector cubre el filtro."""
    if not hubo_vector:
        return SIN_VECTOR_DE_CONSULTA
    if comparados <= 0:
        return FILTRO_SIN_VECTORES
    if comparados < N_MINIMO:
        return GRUPO_CHICO
    return SIN_EVALUAR


def distancia(valor) -> float | None:
    """Distancia coseno redondeada; `None` si no hay (ausencia nunca es cero)."""
    return None if valor is None else round(float(valor), DECIMALES)


def aviso(est: str, comparados: int, hay_semanticos: bool, con_todos_los_terminos: int) -> str | None:
    """Aviso de pertinencia, o None. Solo para `grupo_chico` con resultados por significado en la lista.

    Si además hay fallos que contienen todos los términos buscados (vía literal en su nivel más estricto o frase confirmada), el
    aviso lo dice en vez de contradecirlo: son evidencia por otra vía.
    """
    if est != GRUPO_CHICO or not hay_semanticos:
        return None
    texto = (f"El filtro tiene solo {comparados} fallos con búsqueda por significado: los resultados por significado son los más "
             "parecidos de ese grupo, no necesariamente sobre el punto. Leé los fragmentos antes de concluir, o ampliá el filtro.")
    if con_todos_los_terminos:
        texto += f" Por palabras, {con_todos_los_terminos} de los fallos de la lista contienen todos los términos buscados."
    return texto
