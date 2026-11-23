"""Referencia cifrada en el enlace al sitio: une la visita con quién la hizo y qué buscó.

Controles: sin el aviso v3 el enlace no lleva referencia; una referencia alterada, vencida o inventada no une nada; ni la referencia ni el
invitado van a los logs; el informe encuentra el texto de la búsqueda que originó la visita.
"""

import asyncio
import importlib.util
import logging
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from conector_apoyo import cr

from src.conector import bd, herramientas as H, pantalla, referencia_visita as R, tarjeta_sitio, visitas as V

RAIZ = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("conector_actividad", RAIZ / "scripts" / "conector_actividad.py")
A = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(A)


@pytest.fixture(autouse=True)
def _clave(monkeypatch):
    monkeypatch.setenv("CONECTOR_FIRMA_SECRET", "s" * 48)


def test_la_referencia_se_abre_con_la_llave_y_no_dice_nada_a_simple_vista():
    ref = R.crear("inv-test0001", 1_800_000_000)
    assert "inv-" not in ref and "1800000000" not in ref and len(ref) < 160
    assert R.abrir(ref, 1_800_000_100) == ("inv-test0001", 1_800_000_000)


@pytest.mark.parametrize("cambio", ["alterada", "vencida", "basura", "vacia", "otra_clave"])
def test_una_referencia_que_no_corresponde_no_une_nada(cambio, monkeypatch):
    ref = R.crear("inv-a", 1_800_000_000)
    ahora = 1_800_000_100
    if cambio == "alterada":
        ref = ref[:-2] + ("A" if ref[-2] != "A" else "B") + ref[-1]
    elif cambio == "vencida":
        ahora = 1_800_000_000 + R.VIGENCIA_S + 1
    elif cambio == "basura":
        ref = "x" * 60
    elif cambio == "vacia":
        ref = ""
    else:
        monkeypatch.setenv("CONECTOR_FIRMA_SECRET", "t" * 48)
    assert R.abrir(ref, ahora) is None


def test_el_aviso_vigente_es_el_que_habilita_la_union_y_lo_dice():
    assert pantalla.AVISO_VERSION >= R.AVISO_MINIMO_VISITA
    assert "se anota esa visita junto con la búsqueda que la originó" in pantalla.AVISO_PRIVACIDAD
    # v4 (18-11): el aviso nombra el sitio al que lleva el enlace; el v3 nombraba alejoherrera.com y ya no habilita la unión.
    assert "el enlace a aientika.ai que trae una respuesta" in pantalla.AVISO_PRIVACIDAD and tarjeta_sitio.SITIO.startswith("https://aientika.ai")
    assert not R.corresponde(None) and not R.corresponde(3) and R.corresponde(4)


class _Conexion:
    def close(self):
        pass


@pytest.fixture
def herr(estado_sqlite, monkeypatch):
    monkeypatch.setattr(bd, "conectar_lectura", lambda: _Conexion())
    monkeypatch.setattr(H, "buscar_nucleo", lambda conn, consulta, *a: {"cobertura": "COBERTURA: Datos cargados al 2026-11-15.",
                                                                        "semantica_usada": False, "total": 0, "resultados": [],
                                                                        "solo_literal": [], "aviso": None, "literal": {}})
    return H.Herramientas(reloj=lambda: cr("2026-11-10 09:00"))


def _ref(fuente: str) -> str | None:
    url = fuente.split("](", 1)[1].rstrip(")")
    return parse_qs(urlsplit(url).query).get("r", [None])[0]


def test_con_el_aviso_v4_el_enlace_lleva_la_referencia_del_invitado_y_la_hora(herr):
    r = asyncio.run(herr.buscar("inv-a", "Claude-User", "listas de espera", aviso_version=4))
    ref = _ref(r["fuente"])
    ts = int(cr("2026-11-10 09:00").timestamp())
    assert ref and R.abrir(ref, ts + 60) == ("inv-a", ts)


@pytest.mark.parametrize("aviso", [2, 3])
def test_sin_el_aviso_v4_el_enlace_no_lleva_referencia(herr, aviso):  # control negativo: v3 nombraba otro sitio
    r = asyncio.run(herr.buscar("inv-a", "Claude-User", "listas de espera", aviso_version=aviso))
    assert _ref(r["fuente"]) is None and "utm_source=claude" in r["fuente"]


def _visitas_en_base(ruta):
    with bd.estado() as conn:
        cur = conn.cursor()
        cur.execute("SELECT invitado_id, herramienta, resultado, via, cliente FROM conector_llamada WHERE herramienta = %s", (V.MARCA,))
        return [tuple(f) for f in cur.fetchall()]


def test_la_visita_con_referencia_queda_unida_y_sin_nada_en_los_logs(servidor_http, caplog):
    c, ruta = servidor_http
    ts = int(time.time()) - 30
    ref = R.crear("inv-a", ts)
    with caplog.at_level(logging.INFO):
        r = c.get(V.RUTA, params={"o": "claude", "p": "/agentika.html", "r": ref})
    assert r.status_code == 204
    assert _visitas_en_base(ruta) == [("inv-a", V.MARCA, f"{V.PREFIJO_BUSQUEDA}{ts}", "claude", "/agentika.html")]
    propios = " | ".join(m.getMessage() for m in caplog.records if m.name.startswith("src."))  # el cliente de prueba (httpx) no cuenta
    assert ref not in propios and "inv-a" not in propios
    assert f"{V.MARCA} origen=claude pagina=/agentika.html" in propios  # la línea de siempre sigue para el conteo


def test_la_visita_sin_referencia_o_con_una_inventada_solo_cuenta(servidor_http):  # control negativo
    c, ruta = servidor_http
    assert c.get(V.RUTA, params={"o": "claude", "p": "/agentika.html"}).status_code == 204
    assert c.get(V.RUTA, params={"o": "claude", "p": "/agentika.html", "r": "x" * 60}).status_code == 204
    assert _visitas_en_base(ruta) == []


def test_el_informe_une_la_visita_con_el_texto_de_su_busqueda(estado_sqlite):
    with bd.estado() as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO conector_consulta (ts, invitado_id, herramienta, texto, filtros) VALUES (%s, %s, %s, %s, %s)",
                    (1_000, "inv-a", "buscar", "consulta vieja", None))
        cur.execute("INSERT INTO conector_consulta (ts, invitado_id, herramienta, texto, filtros) VALUES (%s, %s, %s, %s, %s)",
                    (2_000, "inv-a", "buscar", "listas de espera CCSS", None))
        cur.execute("INSERT INTO conector_consulta (ts, invitado_id, herramienta, texto, filtros) VALUES (%s, %s, %s, %s, %s)",
                    (2_001, "inv-b", "buscar", "de otra persona", None))
    V.anotar_unida("inv-a", 2_003, "claude", "/agentika.html", 2_100)
    with bd.estado() as conn:
        lineas = A.visitas(conn.cursor(), 2_200, dias=1)
    assert len(lineas) == 3 and "«listas de espera CCSS»" in lineas[2] and "desde claude a /agentika.html" in lineas[2]
    assert "otra persona" not in "\n".join(lineas) and "consulta vieja" not in "\n".join(lineas)
