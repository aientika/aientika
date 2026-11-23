"""Anonimización de identificadores personales en las búsquedas.

Aiéntika busca por el tema jurídico, no por personas: antes de buscar y antes de guardar el registro de 90 días se reemplazan por
`[dato omitido]` los identificadores que se reconocen sin ambigüedad (cédulas física y jurídica, DIMEX, correos y teléfonos).
Los nombres de persona se reconocen aparte (nombre de pila frecuente más apellidos); los de magistrados se conservan, porque actúan
en función pública. Los demás nombres propios no se tocan: no se distinguen de los de instituciones.

Cuidado con los falsos positivos: números de voto («2026-008822»), expedientes («18-002268-0173-LA»), ids de fallo
(«sen-1-0007-1370745»), años y artículos tienen que quedar intactos. Los tests lo controlan.
"""

from __future__ import annotations

import re

from src.conector.magistrados import es_magistrado

MARCA = "[dato omitido]"
AVISO = ("La búsqueda se anonimizó: se quitaron {n} dato(s) personal(es) (cédula, correo o teléfono). Aiéntika busca por el tema "
         "jurídico, no por personas, y no guarda datos personales en su registro.")

_PATRONES = [
    re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"),                                            # correo
    re.compile(r"(?<![\w-])3-\d{3}-\d{6}(?![\w-])"),                                         # cédula jurídica 3-101-123456
    re.compile(r"(?<![\w-])[1-9]-\d{3,4}-\d{4}(?![\w-])"),                                   # cédula física 1-1234-5678
    re.compile(r"(?<![\w-])[1-9] \d{4} \d{4}(?![\w-])"),                                     # cédula física 1 1234 5678
    re.compile(r"\+506[\s-]?\d{4}[\s-]?\d{4}"),                                              # teléfono con +506
    re.compile(r"(?i)\b(?:tel(?:éfono|efono)?|cel(?:ular)?|whatsapp)\.?:?\s*\d{4}[\s-]?\d{4}\b"),  # teléfono rotulado
    re.compile(r"(?<![\w-])\d{11,12}(?![\w-])"),                                             # DIMEX
    re.compile(r"(?<![\w-])(?:[1-9]\d{8}|3\d{9})(?![\w-])"),                                 # cédula sin guiones (9) o jurídica (10)
    re.compile(r"(?<![\w-])[2-8]\d{7}(?![\w-])"),                                            # teléfono de 8 dígitos sin separador
]


# Nombres de persona (una búsqueda por el nombre de alguien no debe devolver sus procesos). Se reconoce un nombre de pila frecuente
# seguido de 1 a 3 apellidos. Quedan FUERA los nombres que también son palabras jurídicas o comunes (Amparo, Rosa, Luz, Mercedes,
# Pilar, Dolores, Victoria, Cruz, Paz, Socorro, Gracia, Salvador, Ángel, etc.): con ellos el riesgo de borrar un «recurso de amparo» pesa más. Costo aceptado: también se quitan los nombres de magistrados.
_NOMBRES_DE_PILA = set("""
juan jose josé luis carlos jorge manuel antonio francisco javier miguel alejandro andres andrés rafael ricardo roberto
fernando eduardo mario sergio pablo diego daniel david alberto oscar óscar rodrigo gustavo marco marcos esteban adrian adrián
alvaro álvaro arturo enrique ernesto felipe gabriel gerardo guillermo hector héctor hugo ignacio jaime julio leonardo marvin
mauricio olman orlando randall rolando ronald rodolfo victor víctor william walter allan alonso andrey bryan christian cristian
david danny erick gilberth geovanny greivin harold jonathan kevin minor rónald steven johnny jeffrey josue josué santiago
sebastian sebastián tomas tomás vinicio wilberth maria maría ana laura carmen andrea gabriela patricia silvia adriana
alejandra alicia beatriz carolina catalina claudia cristina daniela diana elena eugenia fabiola fernanda flor flora floribeth
grettel hannia ileana iris isabel jacqueline jessica johanna julia karla karen katherine kattia lorena lucia lucía marcela
margarita marta martha melissa monica mónica natalia nuria olga paola priscilla raquel rebeca sandra sara shirley sofia sofía
susana tatiana teresa vanessa veronica verónica viviana ximena yamileth yorleny zeidy marianela marisol rosaura xinia
""".split())
_NO_APELLIDO = set("""
de del la las los el y e o u en por para con sin sobre contra vs versus que a al se su sus fue es demanda recurso amparo
sentencia fallo voto juicio juicios expediente sala tribunal juzgado caso proceso redactor redactora magistrado magistrada
juez jueza abogado abogada actor actora demandado demandada recurrente patrono trabajador trabajadora
""".split())
_PALABRA = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+")


def _anonimizar_nombres(texto: str) -> tuple[str, int]:
    """Reemplaza «nombre de pila + 1 a 3 apellidos» (con «de», «del» o «de la» entre apellidos) por `MARCA`."""
    palabras = [(m.start(), m.end(), m.group()) for m in _PALABRA.finditer(texto)]
    tramos, i = [], 0
    while i < len(palabras):
        if palabras[i][2].lower() not in _NOMBRES_DE_PILA:
            i += 1
            continue
        j, apellidos = i + 1, 0
        mayuscula = palabras[i][2][0].isupper()  # si el nombre viene con mayúscula, los apellidos también (no «despido»)
        while j < len(palabras) and apellidos < 3:
            p = palabras[j][2].lower()
            if p in ("de", "del", "la", "los", "las") and j + 1 < len(palabras) and (
                    palabras[j + 1][2].lower() not in _NO_APELLIDO or palabras[j + 1][2].lower() in ("la", "los", "las")):
                j += 1
                continue
            if p in _NO_APELLIDO or len(p) < 2 or (mayuscula and not palabras[j][2][0].isupper()):
                break
            apellidos += 1
            j += 1
        if apellidos >= 1:
            ini, fin = palabras[i][0], palabras[j - 1][1]
            if not es_magistrado(texto[ini:fin]):  # magistrados: funcionarios públicos en su función (magistrados.py)
                tramos.append((ini, fin))
            i = j
        else:
            i += 1
    for ini, fin in reversed(tramos):
        texto = texto[:ini] + MARCA + texto[fin:]
    return texto, len(tramos)


AVISO_POR_PERSONA = ("Aiéntika no busca por personas: la búsqueda solo traía datos personales (un nombre, una cédula o un "
                     "contacto) y se anonimizó, así que no se ejecutó ni gastó cupo. Aiéntika busca por el tema jurídico; si "
                     "querés jurisprudencia, contá el tema del caso sin nombres.")
_SIN_TEMA = set("""
dame dar buscar busca buscame búscame encontrar encontrame encuentra mostrame muestra listame lista quiero necesito ver los las
el la de del en que a y o un una unos unas aparece aparecen figura figuran sale salen esta está están mencionan menciona sobre
juicios juicio fallos fallo sentencias sentencia resoluciones resolución votos voto casos caso procesos proceso expedientes
expediente demandas demanda todos todas donde dónde cuales cuáles por con para agentika aientika aiéntika ayudame ayúdame
""".split())


def queda_tema(texto: str) -> bool:
    """True si, quitadas las marcas y las palabras de pedido («dame los juicios en que aparece»), queda algún tema que buscar."""
    resto = texto.replace(MARCA, " ")
    return any(len(p) > 2 and p.lower() not in _SIN_TEMA for p in _PALABRA.findall(resto))


def anonimizar(texto: str) -> tuple[str, int]:
    """(texto con los identificadores y nombres de persona reemplazados por `MARCA`, cuántos se reemplazaron)."""
    total = 0
    for patron in _PATRONES:
        texto, n = patron.subn(MARCA, texto)
        total += n
    texto, n = _anonimizar_nombres(texto)
    return texto, total + n
