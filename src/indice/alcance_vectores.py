"""Qué despachos llevan vectores.

Las Salas siempre. Los tribunales, solo en los años en que `extracto.py` quedó validado sobre ellos.
"""

from __future__ import annotations

# Lista escrita a mano: un test la compara con las Salas que ofrece el conector, para que no se desalineen.
DESPACHOS_CON_VECTORES: tuple[str, ...] = (
    "Sala Primera de la Corte",
    "Sala Segunda de la Corte",
    "Sala Tercera de la Corte",
    "Sala Tercera Materia Penal Juvenil",
    "Sala Tercera Penal de Hacienda y Función Pública",
    "Sala Constitucional",
)

# Años en que el extracto quedó validado en tribunales: ahí los tribunales también llevan vectores. Un año entra aquí solo
# después de validar una muestra de sus fallos (2025 sin dispositivas equivocadas; 2023 con el parche para «P O R T A N T O»).
ANNOS_TRIBUNALES_VALIDADOS: tuple[int, ...] = (2025, 2023)

# Fragmento SQL para filtrar por despacho y año: va con los dos parámetros que arma `parametros_filtro`, en ese orden.
FILTRO_DESPACHO = "AND (d.despacho = ANY(%s) OR d.anno = ANY(%s)) "


def parametros_filtro() -> list[list]:
    """Parámetros de `FILTRO_DESPACHO`: [despachos que siempre llevan vectores, años con los tribunales validados]."""
    return [list(DESPACHOS_CON_VECTORES), list(ANNOS_TRIBUNALES_VALIDADOS)]
