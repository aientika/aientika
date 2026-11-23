"""Excepción a la anonimización de nombres: lista de magistrados de las Salas. Son funcionarios públicos en su función: buscar por quien redacta o salva el voto es investigación jurídica.

Fuente: `redactor_metadato` de la base, Salas 2022-2026, nombres con 20 fallos o más. El metadato no es confiable
para saber QUIÉN redactó un fallo concreto, pero sirve para la lista de nombres. Se incluyen las variantes que aparecen en la base
(«Stradtman» y «Stradtmann»). La clave de comparación son los DOS APELLIDOS sin tildes: así vale «Castillo Víquez», «Fernando Castillo
Víquez» o «castillo viquez». Si entra un magistrado nuevo, se suma acá y se agrega a su test.
"""

from __future__ import annotations

import unicodedata

MAGISTRADOS = (
    "Fernando Castillo Víquez", "Jorge Araya García", "Fernando Cruz Castro", "Paul Rueda Leal", "Luis Fernando Salazar Alvarado",
    "Anamari Garro Vargas", "Ingrid Hess Herrera", "Luis Guillermo Rivas Loáiciga", "José Roberto Garita Navarro",
    "Alexandra Alvarado Paniagua", "Jorge Enrique Olaso Álvarez", "Luis Porfirio Sánchez Rodríguez", "Roxana Chacón Artavia",
    "Julia Varela Araya", "Ana María Picado Brenes", "Ana Cristina Fernández Acuña", "Damaris María Vargas Vásquez",
    "Alejandro Delgado Faith", "Ileana Sánchez Navarro", "Rosibel de los Ángeles Jara Velásquez", "Iris Rocío Rojas Morales",
    "Aracelly Pacheco Salazar", "Jorge Isaac de Jesús Solano Aguilar", "Carlos Guillermo Zamora Campos", "Orlando Aguirre Gómez",
    "Ronald Salazar Murillo", "Jorge Leiva Poveda", "Gerardo Rubén Alfaro Vargas", "Hubert Fernández Argüello",
    "Patricia Solano Castro", "Sandra Eugenia Zúñiga Morales", "Rafael Segura Bonilla", "Fernando Enrique Lara Gamboa",
    "Ana Isabel Vargas Vargas", "Jesús Ramírez Quirós", "Patricia Vargas González", "Olman Gerardo Ugalde González",
    "Jéssica Alejandra Jiménez Ramírez", "Ana Patricia Montero Morales", "Rafael Ortega Tellería", "María Angélica Fallas Carvajal",
    "Sandra María Pereira Retana", "Ana Orfilia Briceño Yock", "Miguel Fernández Calvo", "Alexis Fernando Vargas Soto",
    "Rosa Acón Ng", "Rodrigo Campos Esquivel", "Aisen Herrera López", "William Serrano Baby", "Marianela Corrales Pampillo",
    "Giovanni Mena Artavia", "Grace Agüero Alvarado", "Cynthia Dumani Stradtman", "Cynthia Dumani Stradtmann",
    "Eddy Rodríguez Chaves", "Maureen Roxana Solís Madrigal", "Fabián Arrieta Segleau", "Shirley Vanessa Víquez Vargas",
    "Álvaro Burgos Mata", "Deyanira Martínez Bolívar", "Jorge Alberto López González",
)


def _plano(texto: str) -> str:
    """Minúsculas y sin tildes, para comparar «Víquez» con «viquez»."""
    return "".join(c for c in unicodedata.normalize("NFD", texto.lower()) if unicodedata.category(c) != "Mn")


APELLIDOS = {" ".join(_plano(n).split()[-2:]) for n in MAGISTRADOS}


def es_magistrado(tramo: str) -> bool:
    """True si el tramo contiene los dos apellidos de un magistrado de la lista (con o sin nombre de pila)."""
    palabras = _plano(tramo).split()
    pares = {" ".join(palabras[i:i + 2]) for i in range(len(palabras) - 1)}
    return bool(pares & APELLIDOS)
