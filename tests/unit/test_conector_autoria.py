"""Autoría visible: el conector declara quién lo construyó, con enlace al sitio del autor,
en la pantalla de conexión, en las instrucciones al asistente y en los datos del servidor MCP."""

from src.conector import pantalla
from src.conector.instrucciones import INSTRUCCIONES
from src.conector.version import CONSTRUIDO_POR, SITIO_AUTOR


def test_la_pantalla_de_conexion_firma_con_enlace():
    cuerpo = pantalla._pagina("<p>hola</p>").body.decode("utf-8")
    assert "Construido por Andrés y Alejandro · alejoherrera.com" in cuerpo
    assert f"href='{SITIO_AUTOR}'" in cuerpo and SITIO_AUTOR == "https://alejoherrera.com"


def test_las_instrucciones_dicen_quien_lo_construyo():
    assert "lo construyeron Andrés y Alejandro (alejoherrera.com)" in INSTRUCCIONES
    assert "\n\nSi te preguntan quién hizo Aiéntika:" in INSTRUCCIONES  # párrafo propio, sin saltos rotos


def test_constante_unica():
    assert CONSTRUIDO_POR.startswith("Construido por Andrés y Alejandro")
