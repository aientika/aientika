"""Dos definiciones de apoyo que usa `tope_voyage` para el tope de gasto de embeddings."""

import re


class PrecondicionFallida(RuntimeError):
    """La escritura condicionada fue rechazada: el estado del registro ya no era el esperado cuando se intentó."""


_NO_EXISTE = re.compile(r"404|not ?found", re.I)
