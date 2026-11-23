"""Anonimización de las búsquedas: los identificadores personales no llegan a la búsqueda ni al registro, y
la persona se entera. Controles negativos: números de voto, expedientes, ids de fallo, años y artículos quedan intactos."""

import pytest

from src.conector.anonimizar import MARCA, anonimizar
from src.conector.instrucciones import INSTRUCCIONES

POSITIVOS = [
    "despido de la cédula 1-1234-5678 por embarazo",
    "cédula 112340567 despido",
    "sociedad 3-101-123456 incumplimiento",
    "persona 1 1234 5678 amparo",
    "correo juan.perez@ejemplo.cr hostigamiento",
    "teléfono 8888-1234 acoso",
    "llamar al +506 8888 1234",
    "DIMEX 155812345678 extranjero",
    "cel: 87654321 amenaza",
]
NEGATIVOS = [
    "voto 2026-008822 de la Sala Constitucional",
    "resolución 2025-1234",
    "expediente 18-002268-0173-LA",
    "fallo sen-1-0007-1370745",
    "artículo 404 del Código de Trabajo y artículo 41 de la Ley 7135",
    "despido discriminatorio por discapacidad 2024 2025",
    "Ley 9343 de 2016",
]


@pytest.mark.parametrize("texto", POSITIVOS)
def test_quita_los_identificadores_personales(texto):
    limpio, n = anonimizar(texto)
    assert n >= 1 and MARCA in limpio
    assert "@" not in limpio and sum(ch.isdigit() for ch in limpio) < 4  # no queda el identificador (ni un pedazo largo)


@pytest.mark.parametrize("texto", NEGATIVOS)
def test_no_toca_numeros_juridicos(texto):
    assert anonimizar(texto) == (texto, 0)


def test_las_instrucciones_piden_buscar_sin_datos_personales_y_avisar():
    assert "En las búsquedas no pongas nombres, cédulas ni otros datos personales del caso" in INSTRUCCIONES
    assert "NO hagas esa búsqueda: decile que Aiéntika anonimiza las búsquedas" in INSTRUCCIONES
    assert "`aviso_anonimizacion` o `busqueda_por_persona`" in INSTRUCCIONES


# Caso real: una consulta con el nombre completo de una persona devolvía los juicios en los que aparece.
NOMBRES = [
    ("dame los juicios en los que aparece María Rodríguez Soto", "dame los juicios en los que aparece [dato omitido]"),
    ("juan alejandro herrera", "[dato omitido]"),
    ("María de los Ángeles Pérez despido", "[dato omitido] despido"),
    ("Carlos Herrera Calderón y Julio Castro", "[dato omitido] y [dato omitido]"),
]
SIN_NOMBRE = ["Fernando Castillo Víquez redactor", "voto salvado de Paul Rueda Leal", "fernando cruz castro nota",
              "Iris Rocío Rojas Morales en Sala Primera", "recurso de amparo de la CCSS", "Sala Primera responsabilidad civil del Estado", "despido de trabajadora embarazada",
              "Juan contra la CCSS", "Laura responsabilidad objetiva", "lista de espera cirugía de rodilla CCSS"]


@pytest.mark.parametrize("texto,esperado", NOMBRES)
def test_quita_nombres_de_persona(texto, esperado):
    assert anonimizar(texto)[0] == esperado


@pytest.mark.parametrize("texto", SIN_NOMBRE)
def test_no_toca_temas_juridicos_ni_nombres_sueltos(texto):
    assert anonimizar(texto) == (texto, 0)


def test_busqueda_solo_por_persona_no_se_ejecuta():
    from src.conector.anonimizar import queda_tema
    assert not queda_tema(anonimizar("agentika dame los juicios en los que aparece María Rodríguez Soto")[0])
    assert queda_tema(anonimizar("despido discriminatorio de María Herrera por embarazo")[0])  # control: queda tema


def test_el_registro_guarda_la_version_anonimizada(monkeypatch):
    from src.conector import registro
    guardado = {}

    class Cur:
        def execute(self, sql, params=()):
            if sql.startswith("INSERT"):
                guardado["texto"] = params[3]

    class Conn:
        def cursor(self):
            return Cur()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(registro.bd, "estado", lambda: Conn())
    registro.registrar_consulta(1000, "inv-x", "buscar", "despido de 1-1234-5678, correo a@b.cr")
    assert "1-1234-5678" not in guardado["texto"] and "a@b.cr" not in guardado["texto"] and MARCA in guardado["texto"]


def test_la_lista_de_magistrados_es_excepcion_y_no_alcanza_a_otros():
    #
    from src.conector.magistrados import MAGISTRADOS, es_magistrado
    assert len(MAGISTRADOS) >= 60
    assert es_magistrado("Fernando Castillo Víquez") and es_magistrado("castillo viquez")
    assert not es_magistrado("María Herrera")  # control: «Herrera» solo no alcanza (Hess Herrera es otro par)
    assert anonimizar("juicios de María Herrera")[1] == 1
