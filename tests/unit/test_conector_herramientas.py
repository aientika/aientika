"""Embudo de las herramientas: horario, cupo antes de ejecutar, errores en palabras (nunca «cero resultados»), registro SIN texto de la consulta.

El núcleo (`buscar`, `ficha`, `verificar_cita`) se sustituye por funciones que devuelven o lanzan lo que haría la base real; el
núcleo ya tiene sus propios tests. Aquí se prueba lo que añade esta capa. `FRASE_MARCADA` es una frase centinela: no debe aparecer en el registro.
"""

import asyncio

import pytest
from conector_apoyo import cr, volcar_tablas

from src.conector import bd, herramientas as H, limites as L
from src.conector.ficha import DocumentoNoEncontrado
from src.conector.version import CONECTOR_VERSION
from src.indice.embeber_voyage import ErrorVoyage

FRASE_MARCADA = "ZXQ-frase-marcada-confidencial-9917"
RESPUESTA = {"cobertura": "COBERTURA: prueba.", "semantica_usada": True, "total": 1, "resultados": [{"id": "sen-1-0001-0000001"}],
             "solo_literal": [], "aviso": None, "literal": {}}


class ConexionFalsa:
    def close(self):
        pass


@pytest.fixture
def h(estado_sqlite, monkeypatch):
    """Herramientas con reloj a las 09:00 CR, base falsa y núcleo sustituible. Devuelve (Herramientas, llamadas al núcleo)."""
    llamadas = []
    monkeypatch.setattr(bd, "conectar_lectura", lambda: ConexionFalsa())
    monkeypatch.setattr(H, "buscar_nucleo", lambda conn, consulta, *a: llamadas.append(consulta) or dict(RESPUESTA))
    return H.Herramientas(embeber=lambda q: [0.0] * 1024, reloj=lambda: cr("2026-11-10 09:00")), llamadas


def correr(coro):
    return asyncio.run(coro)


def test_buscar_devuelve_la_cobertura_primero_y_lo_que_queda_del_cupo(h):
    herr, llamadas = h
    r = correr(herr.buscar("inv-a", None, "responsabilidad civil"))
    assert list(r)[0] == "cobertura" and r["via"] == "semantica+literal" and r["total"] == 1
    assert f"{L.BUSCAR_POR_VENTANA - 1} de {L.BUSCAR_POR_VENTANA}" in r["cupo"]
    assert llamadas == ["responsabilidad civil"]


def test_buscar_trae_la_linea_de_fuente_lista_con_el_enlace_al_sitio(h):
    # Claude y ChatGPT no remitían al sitio con la instrucción sola; la línea va en el resultado de cada búsqueda.
    herr, _ = h
    r = correr(herr.buscar("inv-a", "Claude-User", "responsabilidad civil"))
    assert r["fuente"].startswith("Fuente: base de Aiéntika (datos al ")
    assert "Conocé más en [aientika.ai](https://aientika.ai/?utm_source=claude" in r["fuente"]  # sitio propio desde el 18-11
    assert "alejoherrera.com" not in r["fuente"]
    assert r["fuente"].endswith(")")  # el enlace markdown cierra: clickeable
    assert "tal cual" in r["fuente_instruccion"]


def test_buscar_por_datos_personales_busca_anonimizado_y_lo_avisa(h):
    #
    herr, llamadas = h
    r = correr(herr.buscar("inv-a", None, "despido de la cédula 1-1234-5678 por embarazo"))
    assert llamadas == ["despido de la cédula [dato omitido] por embarazo"]  # la base nunca vio la cédula
    assert "se anonimizó" in r["aviso_anonimizacion"]
    r2 = correr(herr.buscar("inv-a", None, "despido por embarazo"))  # control: sin datos personales no hay aviso
    assert "aviso_anonimizacion" not in r2
    r3 = correr(herr.buscar("inv-a", None, "agentika dame los juicios en los que aparece María Rodríguez Soto"))
    assert r3["busqueda_por_persona"] and r3["resultados"] == [] and "no busca por personas" in r3["aviso_anonimizacion"]
    assert len(llamadas) == 2  # la búsqueda por persona no llegó a la base


def test_fuera_de_horario_se_dice_y_no_se_toca_la_base(estado_sqlite, monkeypatch):
    monkeypatch.setattr(L, "SERVICIO_24_HORAS", False)  # el horario de 7 a 23 queda como vuelta atrás
    monkeypatch.setattr(bd, "conectar_lectura", lambda: pytest.fail("no debía abrir la base fuera de horario"))
    herr = H.Herramientas(reloj=lambda: cr("2026-11-10 02:00"))
    for llamada in (herr.buscar("i", None, "algo"), herr.ficha("i", None, "x"), herr.ayuda("i", None)):
        r = correr(llamada)
        assert r["error"] == "fuera_de_horario" and "7:00 a 23:00" in r["mensaje"] and "hora de Costa Rica" in r["mensaje"]
    assert "uso: []" in volcar_tablas(estado_sqlite)


def test_agotado_el_cupo_no_se_ejecuta_y_se_dice_la_hora(h):
    herr, llamadas = h
    for _ in range(L.BUSCAR_POR_VENTANA):
        correr(herr.buscar("inv-a", None, "consulta"))
    r = correr(herr.buscar("inv-a", None, "consulta"))
    assert r["error"] == "limite_alcanzado" and "12:00" in r["mensaje"]
    assert len(llamadas) == L.BUSCAR_POR_VENTANA  # la llamada rechazada no ejecutó nada


def test_llamadas_en_paralelo_no_ejecutan_mas_que_el_cupo(h):
    herr, llamadas = h

    async def rafaga():
        return await asyncio.gather(*[herr.buscar("inv-a", None, f"consulta{i}") for i in range(L.BUSCAR_POR_VENTANA + 10)])

    res = asyncio.run(rafaga())
    assert sum("error" not in r for r in res) == L.BUSCAR_POR_VENTANA and len(llamadas) == L.BUSCAR_POR_VENTANA


def test_base_caida_es_un_error_en_palabras_no_cero_resultados_y_devuelve_la_unidad(h, monkeypatch):
    herr, _ = h
    herr.embeber = None  # sin Voyage de por medio la unidad vuelve; con Voyage gastado no
    def caida():
        raise bd.BDNoDisponible("OSError")
    monkeypatch.setattr(bd, "conectar_lectura", caida)
    r = correr(herr.buscar("inv-a", None, "consulta"))
    assert r["error"] == "base_no_disponible" and r["quien"] == "servicio" and "no es que no haya resultados" in r["mensaje"].lower()
    assert "resultados" not in r and "total" not in r
    assert L.consumir("buscar", "inv-a", cr("2026-11-10 09:00")).cupo.startswith(f"Te quedan {L.BUSCAR_POR_VENTANA - 1} de")


@pytest.mark.parametrize("excepcion,tipo", [(RuntimeError("boom"), "error_interno")])
def test_error_interno_del_embebido_es_un_error_explicito(h, excepcion, tipo):
    # Los fallos de Voyage (ErrorVoyage, presupuesto, opt-out, clave) ya no son un error: buscar sigue por la vía literal y lo declara.
    herr, _ = h

    def embeber(q):
        raise excepcion
    herr.embeber = embeber
    r = correr(herr.buscar("inv-a", None, "consulta"))
    assert r["error"] == tipo and "resultados" not in r


def test_error_de_la_entrada_se_explica_y_gasta_la_unidad(h):
    herr, _ = h
    r = correr(herr.buscar("inv-a", None, "consulta", desde="ayer"))
    assert r["error"] == "entrada_invalida" and r["quien"] == "usuario" and "AAAA-MM-DD" in r["mensaje"]
    # la unidad NO se devuelve ante un error del usuario (así una ráfaga de entradas inválidas topa igual)
    assert L.consumir("buscar", "inv-a", cr("2026-11-10 09:00")).cupo.startswith(f"Te quedan {L.BUSCAR_POR_VENTANA - 2} de")


def test_ficha_inexistente_se_dice_y_no_es_una_ficha_vacia(h, monkeypatch):
    herr, _ = h

    def no(conn, id):
        raise DocumentoNoEncontrado(id)
    monkeypatch.setattr(H, "ficha_nucleo", no)
    r = correr(herr.ficha("inv-a", None, "sen-1-9999-9999999"))
    assert r["error"] == "no_encontrado" and "id" in r["mensaje"]


def test_ayuda_no_gasta_cupo_y_si_la_base_cae_lo_dice(h, monkeypatch):
    herr, _ = h
    monkeypatch.setattr(H, "cobertura", lambda c: {"linea": "COBERTURA: 2025 por significado."})
    r = correr(herr.ayuda("inv-a", None))
    assert r["version_conector"] == CONECTOR_VERSION and "COBERTURA" in r["cobertura"] and r["cupo"]["buscar:v4h"]["quedan"] == L.BUSCAR_POR_VENTANA
    monkeypatch.setattr(bd, "conectar_lectura", lambda: (_ for _ in ()).throw(bd.BDNoDisponible("OSError")))
    r = correr(herr.ayuda("inv-a", None))
    assert "NO DISPONIBLE" in r["cobertura"] and "no es una cobertura vacía" in r["cobertura"].lower()


def test_reportar_guarda_el_reporte_y_exige_contenido(h):
    herr, _ = h
    assert correr(herr.reportar("inv-a", None, "pedí X y llegó Y", "no sirve"))["estado"] == "recibido"
    assert correr(herr.reportar("inv-a", None, " ", "no sirve"))["error"] == "entrada_invalida"


# ---: ni una frase de consulta en logs ni en tablas -------------------------------------------------------------------

def test_qa11_la_frase_marcada_no_queda_en_logs_ni_en_tablas_ni_en_errores(h, estado_sqlite, logs, monkeypatch):
    herr, _ = h
    correr(herr.buscar("inv-a", "cli", f"derecho {FRASE_MARCADA}"))

    def estalla(conn, consulta, *a):  # un error de tsquery de Postgres repite la consulta en su mensaje
        raise RuntimeError(f'syntax error in tsquery: "{consulta}"')
    monkeypatch.setattr(H, "buscar_nucleo", estalla)
    r = correr(herr.buscar("inv-a", "cli", f"derecho {FRASE_MARCADA}"))
    assert r["error"] == "error_interno" and FRASE_MARCADA not in str(r)

    def estalla_voyage(q):
        raise ErrorVoyage(f"HTTP 400: {q}")
    herr.embeber = estalla_voyage
    assert FRASE_MARCADA not in str(correr(herr.buscar("inv-a", "cli", f"derecho {FRASE_MARCADA}")))
    assert logs and any("falló buscar" in linea for linea in logs)  # control positivo: sí se loguea, pero solo el tipo
    assert not [linea for linea in logs if FRASE_MARCADA in linea]
    assert FRASE_MARCADA not in volcar_tablas(estado_sqlite)
    assert "conector_llamada" in volcar_tablas(estado_sqlite) and "buscar" in volcar_tablas(estado_sqlite)  # el registro sí escribió


def test_qa11_la_verificacion_de_una_frase_tampoco_se_guarda(h, estado_sqlite, logs, monkeypatch):
    herr, _ = h
    monkeypatch.setattr(H, "verificar_nucleo", lambda conn, id, frase: {"id": id, "literal": False, "veredicto": "NO_LITERAL"})
    correr(herr.verificar_cita("inv-a", "cli", "sen-1-0001-0000001", f"{FRASE_MARCADA} es una frase suficientemente larga"))
    assert FRASE_MARCADA not in volcar_tablas(estado_sqlite) and not [x for x in logs if FRASE_MARCADA in x]


def test_el_registro_no_tiene_ninguna_columna_de_texto_de_consulta(estado_sqlite):
    with bd.estado() as conn:
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(conector_llamada)")
        columnas = {f[1] for f in cur.fetchall()}
    assert columnas == {"ts", "invitado_id", "herramienta", "resultado", "duracion_ms", "n_resultados", "via", "cliente", "version"}


def test_si_el_registro_falla_la_llamada_igual_se_contesta_y_queda_un_aviso(h, logs, monkeypatch):
    herr, _ = h
    from src.conector import registro
    monkeypatch.setattr(registro.bd, "estado", lambda: (_ for _ in ()).throw(RuntimeError(f"fallo con {FRASE_MARCADA}")))
    monkeypatch.setattr(L, "consumir", lambda *a, **k: L.Veredicto(True))
    r = correr(herr.buscar("inv-a", None, "consulta"))
    assert r["total"] == 1
    avisos = [x for x in logs if "conector-registro" in x]
    assert avisos and not [x for x in logs if FRASE_MARCADA in x]


def test_ayuda_dice_quien_construyo_el_conector(h, monkeypatch):
    #
    herr, _ = h
    monkeypatch.setattr(H, "cobertura", lambda c: {"linea": "COBERTURA: 2025 por significado."})
    assert correr(herr.ayuda("inv-a", None))["construido_por"] == "Construido por Andrés y Alejandro · alejoherrera.com"
