"""Correcciones en la capa de herramientas: validación de entrada, búsqueda sin Voyage, formato de la respuesta y las bajas de entrada y de tope.

Validación: la entrada se valida ANTES de llamar a Voyage, y una vez llamado Voyage la unidad no se devuelve nunca. Sin Voyage la búsqueda
sigue por la vía literal y LO DICE.
"""

import asyncio

import pytest
from conector_apoyo import cr

from src.conector import bd, buscar as B, herramientas as H, limites as L, presupuesto_voyage as P
from src.indice.embeber_voyage import ErrorVoyage
from src.indice.tope_voyage import SinOptOut

RESPUESTA = {"cobertura": "COBERTURA: prueba.", "semantica_usada": False, "total": 1, "resultados": [{"id": "sen-1-0001-0000001"}],
             "solo_literal": [], "aviso": None, "literal": {}}
AHORA = cr("2026-11-10 09:00")


class ConexionFalsa:
    def close(self):
        pass


def correr(coro):
    return asyncio.run(coro)


def quedan(invitado="inv-a") -> str:
    """Lo que el cupo dice que queda (consume una unidad para leerlo, igual que los demás tests)."""
    return L.consumir("buscar", invitado, AHORA).cupo


@pytest.fixture
def contexto(estado_sqlite, monkeypatch):
    """(Herramientas, embebidos a Voyage, llamadas al núcleo). El núcleo real valida; la base es falsa."""
    embebidos, llamadas = [], []
    monkeypatch.setattr(bd, "conectar_lectura", lambda: ConexionFalsa())

    def nucleo(conn, consulta, despacho, anno, desde, hasta, vector):
        B.validar_entrada(consulta, desde, hasta)
        llamadas.append(vector)
        return dict(RESPUESTA, semantica_usada=vector is not None)

    monkeypatch.setattr(H, "buscar_nucleo", nucleo)

    def embeber(q):
        embebidos.append(q)
        return [0.0] * 1024

    return H.Herramientas(embeber=embeber, reloj=lambda: AHORA), embebidos, llamadas


# --- validación de entrada -------------------------------------------------------------------------------------------------------------------------

def test_una_consulta_sin_terminos_utiles_no_llega_a_voyage_y_el_cupo_igual_topa(contexto):
    herr, embebidos, _ = contexto
    sin_terminos = " ".join(["ab"] * 660)  # pasa el tope de 2.000 caracteres pero no tiene una sola palabra útil
    res = [correr(herr.buscar("inv-a", None, sin_terminos)) for _ in range(L.BUSCAR_POR_VENTANA * 4)]
    assert embebidos == []  # antes del arreglo: 60 llamadas a Voyage
    assert {r["error"] for r in res} == {"entrada_invalida", "limite_alcanzado"}
    assert sum(r["error"] == "entrada_invalida" for r in res) == L.BUSCAR_POR_VENTANA  # la unidad se gasta: el cupo SÍ topa


@pytest.mark.parametrize("args", [{"consulta": "   "}, {"consulta": "de la y"}, {"consulta": "algo valido", "desde": "ayer"},
                                  {"consulta": "algo valido", "hasta": "2025-W01-1"}, {"consulta": "algo valido", "desde": "20250101"},
                                  {"consulta": "x" * 2100}, {"consulta": '"uno dos" "tres cuatro" "cinco seis" "siete ocho"'}])
def test_toda_entrada_invalida_se_rechaza_antes_de_embeber(contexto, args):
    herr, embebidos, _ = contexto
    r = correr(herr.buscar("inv-a", None, **args))
    assert r["error"] == "entrada_invalida" and r["quien"] == "usuario" and embebidos == []


def test_control_positivo_una_entrada_valida_si_embebe(contexto):
    herr, embebidos, llamadas = contexto
    r = correr(herr.buscar("inv-a", None, "responsabilidad civil", desde="2025-01-31"))
    assert "error" not in r and embebidos == ["responsabilidad civil"] and len(llamadas) == 1


def test_un_error_de_entrada_no_devuelve_la_unidad(contexto):
    herr, _, _ = contexto
    correr(herr.buscar("inv-a", None, "de la y"))
    assert quedan() == f"Te quedan {L.BUSCAR_POR_VENTANA - 2} de {L.BUSCAR_POR_VENTANA} búsquedas en esta ventana (se renueva hoy a las 12:00) " \
                       f"y {L.BUSCAR_POR_SEMANA - 2} de {L.BUSCAR_POR_SEMANA} esta semana (hora de Costa Rica)."


def test_un_value_error_del_nucleo_tras_embeber_no_devuelve_la_unidad(contexto, monkeypatch):
    herr, embebidos, _ = contexto

    def nucleo(*a):
        raise ValueError("el núcleo rechazó la consulta")
    monkeypatch.setattr(H, "buscar_nucleo", nucleo)
    r = correr(herr.buscar("inv-a", None, "responsabilidad civil"))
    assert r["error"] == "entrada_invalida" and embebidos == ["responsabilidad civil"]
    assert quedan().startswith(f"Te quedan {L.BUSCAR_POR_VENTANA - 2} de")


def test_un_fallo_del_servicio_tras_gastar_voyage_tampoco_devuelve_la_unidad(contexto, monkeypatch):
    herr, embebidos, _ = contexto
    monkeypatch.setattr(bd, "conectar_lectura", lambda: (_ for _ in ()).throw(bd.BDNoDisponible("OSError")))
    r = correr(herr.buscar("inv-a", None, "responsabilidad civil"))
    assert r["error"] == "base_no_disponible" and len(embebidos) == 1
    assert quedan().startswith(f"Te quedan {L.BUSCAR_POR_VENTANA - 2} de")


def test_control_positivo_un_fallo_del_servicio_sin_voyage_si_devuelve_la_unidad(contexto, monkeypatch):
    herr, _, _ = contexto
    herr.embeber = None  # nada se gastó en Voyage: la base cayó antes de buscar
    monkeypatch.setattr(bd, "conectar_lectura", lambda: (_ for _ in ()).throw(bd.BDNoDisponible("OSError")))
    assert correr(herr.buscar("inv-a", None, "responsabilidad civil"))["error"] == "base_no_disponible"
    assert quedan().startswith(f"Te quedan {L.BUSCAR_POR_VENTANA - 1} de")


# --- búsqueda sin Voyage -------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("excepcion,motivo", [(P.PresupuestoAgotado("x"), "presupuesto_agotado"), (ErrorVoyage("HTTP 500"), "embebido_no_disponible"),
                                              (SinOptOut("falta"), "embebido_no_disponible"), (KeyError("VOYAGE_API_KEY"), "embebido_no_disponible")])
def test_sin_voyage_buscar_responde_por_la_via_literal_y_lo_declara(contexto, excepcion, motivo):
    herr, _, llamadas = contexto

    def embeber(q):
        raise excepcion
    herr.embeber = embeber
    r = correr(herr.buscar("inv-a", None, "responsabilidad civil"))
    assert "error" not in r and r["resultados"] and r["via"] == "literal" and r["semantica_usada"] is False
    assert r["semantica_no_disponible"] == motivo and "solo literales" in r["aviso"] and llamadas == [None]
    assert list(r)[0] == "cobertura"


def test_control_un_error_inesperado_del_embebido_sigue_siendo_un_error_explicito(contexto):
    herr, _, _ = contexto

    def embeber(q):
        raise RuntimeError("boom")
    herr.embeber = embeber
    r = correr(herr.buscar("inv-a", None, "responsabilidad civil"))
    assert r["error"] == "error_interno" and "resultados" not in r


def test_el_aviso_del_nucleo_se_conserva_junto_al_de_la_degradacion(contexto, monkeypatch):
    herr, _, _ = contexto
    monkeypatch.setattr(H, "buscar_nucleo", lambda *a: dict(RESPUESTA, total=0, resultados=[], aviso="Sin resultados en lo cargado."))
    herr.embeber = lambda q: (_ for _ in ()).throw(P.PresupuestoAgotado("x"))
    r = correr(herr.buscar("inv-a", None, "responsabilidad civil"))
    assert "presupuesto" in r["aviso"] and "Sin resultados en lo cargado." in r["aviso"]


# --- formato de la respuesta -------------------------------------------------------------------------------------------------------------------------

def test_los_fragmentos_se_arman_con_a_lo_sumo_los_terminos_mas_largos(monkeypatch):
    vistos = []
    # 1.3.0: `armar` recibe además el despacho fase A: los rótulos del fondo dependen de la Sala)
    monkeypatch.setattr(B, "armar", lambda texto, terms, via, despacho=None: vistos.append(list(terms)) or {})
    monkeypatch.setattr(B, "identificacion", lambda *a: {"numero": "1", "fecha": None, "expediente": None})
    consulta = "or ".join(f"palabra{i:03d} " for i in range(188))
    ts = B.terminos(consulta)
    assert len(ts) == 188  # control positivo: la consulta sí trae cientos de términos
    B._resultado(("id", "d", "SNT", 1, None, None, "texto"), "literal", ts)
    assert len(vistos[0]) == B.TOPE_TERMINOS
    B._resultado(("id", "d", "SNT", 1, None, None, "texto"), "literal", ["uno", "dos"])
    assert vistos[1] == ["uno", "dos"]  # pocos términos: pasan todos


def test_el_tope_deja_los_mas_largos_en_su_orden():
    ts = ["corto", "unapalabramuylarga", "med", "otrapalabralarga", "x1", "x2", "x3", "x4", "x5", "x6"]
    elegidos = B._terminos_de_fragmentos(ts)
    assert len(elegidos) == B.TOPE_TERMINOS and elegidos.index("unapalabramuylarga") < elegidos.index("otrapalabralarga")
    assert "x6" not in elegidos


# --- bajas -----------------------------------------------------------------------------------------------------------------------

def test_baja1_verificar_cita_entra_al_tope_global():
    glob = [r for r in L.reglas("verificar_cita", "inv-a", AHORA) if r.global_]
    assert len(glob) == 1 and glob[0].tope == L.TOPE_GLOBAL_DIA
    assert [r.global_ for r in L.reglas("ficha", "inv-a", AHORA)] == [False, True]  # control: ficha ya entraba


def test_baja2_ayuda_tiene_su_tope_diario(contexto, monkeypatch):
    herr, _, _ = contexto
    monkeypatch.setattr(H, "cobertura", lambda c: {"linea": "COBERTURA: x"})
    monkeypatch.setattr(L, "AYUDA_POR_DIA", 3)
    res = [correr(herr.ayuda("inv-a", None)) for _ in range(5)]
    assert [("error" in r) for r in res] == [False, False, False, True, True] and res[3]["error"] == "limite_alcanzado"
    assert "error" not in correr(herr.ayuda("inv-b", None))  # el tope es por invitado
    assert quedan().startswith(f"Te quedan {L.BUSCAR_POR_VENTANA - 1} de")  # ayuda no gasta búsquedas


def test_baja5_los_parametros_enormes_se_rechazan_en_la_frontera(contexto):
    herr, _, _ = contexto
    assert correr(herr.ficha("inv-a", None, "x" * 5000))["error"] == "entrada_invalida"
    assert correr(herr.verificar_cita("inv-a", None, "sen-1", "y" * 100_000))["error"] == "entrada_invalida"
    assert correr(herr.reportar("inv-a", None, "r" * 5000, "p"))["error"] == "entrada_invalida"
    assert correr(herr.buscar("inv-a", None, "responsabilidad civil", despacho="d" * 500))["error"] == "entrada_invalida"
