"""Cortador de considerandos y partición en oraciones para `secciones_fondo`.

Un considerando de primer nivel empieza en un numeral romano en mayúsculas que continúa la secuencia I, II, III… Si la
secuencia no cierra (salto, reinicio fuera de un bloque «AGRAVIOS:», ningún candidato), el fallo no tiene tramos y todo queda
neutro: es costo de utilidad aceptado, nunca una afirmación. El detector de transcripción por comillas NO se usa (30 de 72
fallos de la muestra tienen aperturas y cierres desbalanceados).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

MAYUSCULA = "A-ZÁÉÍÓÚÑ"
_ROMANO = r"((?:XL|L?X{0,3})(?:IX|IV|V?I{0,3}))"
# Separador del numeral: «.», «-», «–», «.-», «.–» (con un espacio opcional entre punto y guion, como «I. –» de la Segunda),
# y luego espacio opcional y una mayúscula, una comilla o «[». Con esto «Tomo II.», «Garro V.», «José I.», «la X.F.» y
# «considerando XXIII.» no son candidatos: no van tras fin de oración ni tras salto de línea.
_SEPARADOR = r"(?:\.\s?[-–]|[.\-–])\s*(?=[" + MAYUSCULA + r"\"\[])"
# Tras fin de oración («.», «:», «;», comilla) y espacio, o tras salto de línea (título en renglón propio sin punto:
# «Recurso de nulidad de Mabinsa⏎II.-», «Motivos procesales⏎IX.»).
_CANDIDATO = re.compile(r"(?:(?<=[.:;\"»]\s)|(?<=[.:;\"»]\s\s)|(?<=\n))" + _ROMANO + _SEPARADOR)
# Al inicio de la zona: inmediatamente después de la palabra «Considerando» y su puntuación («CONSIDERANDO: I.-»).
_CANDIDATO_INICIAL = re.compile(r"\s*[:.\-–]*\s*" + _ROMANO + _SEPARADOR)
# Bloques de agravios de la Sala Segunda al inicio de un considerando («II.- AGRAVIOS:»). «SOBRE LOS AGRAVIOS…» no abre.
BLOQUE_SEGUNDA = re.compile(r"(?:AGRAVIOS|RECURSOS?\s+DE\s+CASACI[OÓ]N|RECURSO\s+DE\s+LA\s+PARTE\s+[" + MAYUSCULA + r" ]+)\s*:")
_VALOR = {"I": 1, "V": 5, "X": 10, "L": 50}
MAXIMO_NUMERAL = 50
# Fin de oración: «.» o «:» seguido de espacio y (opcionalmente) comilla, signo de apertura o paréntesis, y mayúscula.
_FIN_ORACION = re.compile(r"[.:](?=\s+[\"¿¡(]?[" + MAYUSCULA + r"])")


@dataclass(frozen=True)
class Considerando:
    """Un considerando de primer nivel: numeral en `inicio`, texto desde `cuerpo` hasta `fin` (siguiente numeral o zona)."""
    numero: int
    inicio: int
    cuerpo: int
    fin: int
    bloque: bool = False  # abre un bloque «AGRAVIOS:» (o variante) de la Sala Segunda


def romano(s: str) -> int:
    """Valor de un numeral romano ya validado por la regex."""
    total = 0
    for i, c in enumerate(s):
        v = _VALOR[c]
        total += -v if i + 1 < len(s) and _VALOR[s[i + 1]] > v else v
    return total


def candidatos(texto: str, ini: int, fin: int, fin_palabra: int) -> list[tuple[int, int, int]]:
    """[(posición del numeral, posición del cuerpo, valor)] en [ini, fin), en orden. `fin_palabra`: fin de «Considerando»."""
    salida = []
    m = _CANDIDATO_INICIAL.match(texto, fin_palabra)
    if m and m.group(1) and m.start(1) < fin:
        salida.append((m.start(1), m.end(), romano(m.group(1))))
    for m in _CANDIDATO.finditer(texto, ini, fin):
        if m.group(1) and (not salida or m.start(1) > salida[0][0]):
            salida.append((m.start(1), m.end(), romano(m.group(1))))
    return [c for c in salida if 0 < c[2] <= MAXIMO_NUMERAL]


def cortar(texto: str, ini: int, fin: int, fin_palabra: int, con_bloques: bool) -> list[Considerando] | None:
    """Considerandos de primer nivel en [ini, fin); None si la secuencia no cierra.

    Dentro de un bloque «AGRAVIOS:» de la Segunda (`con_bloques`), los numerales que no continúan la secuencia externa abren o
    continúan una secuencia interna; el bloque termina en el primer candidato que continúa la externa y no la interna
    (sen-1-0034-1431950: agravios internos I a VI dentro del «II.- AGRAVIOS:», y luego el «III.-» real).
    """
    cands = candidatos(texto, ini, fin, fin_palabra)
    if not cands:
        return None
    hallados: list[tuple[int, int, int, bool]] = []
    externo, interno, en_bloque = 1, 1, False
    for pos, cuerpo, n in cands:
        if en_bloque and n == interno:
            interno += 1
            continue
        if n != externo:
            return None
        cabeza = texto[cuerpo:cuerpo + 120]
        en_bloque = con_bloques and bool(BLOQUE_SEGUNDA.match(cabeza)) and not cabeza.upper().startswith("SOBRE")
        hallados.append((n, pos, cuerpo, en_bloque))
        externo, interno = externo + 1, 1
    return [Considerando(n, pos, cuerpo, hallados[k + 1][1] if k + 1 < len(hallados) else fin, bloque)
            for k, (n, pos, cuerpo, bloque) in enumerate(hallados)]


def oraciones(texto: str, a: int, b: int) -> list[tuple[int, int]]:
    """[(inicio, fin)] de las oraciones de [a, b), sin el espacio inicial: corte en «.» o «:» seguido de espacio y mayúscula."""
    salida, i = [], a
    for m in _FIN_ORACION.finditer(texto, a, b):
        salida.append((i, m.end()))
        i = m.end()
    if i < b:
        salida.append((i, b))
    limpias = []
    for x, y in salida:
        while x < y and texto[x].isspace():
            x += 1
        if x < y:
            limpias.append((x, y))
    return limpias
