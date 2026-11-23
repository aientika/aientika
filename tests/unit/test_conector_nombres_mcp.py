"""Contrato 2.0.0: los nombres MCP dicen país y contenido, y ningún texto que lee
Claude nombra una herramienta por su nombre viejo. Un nombre genérico como `buscar` no se encuentra entre las herramientas
diferidas del cliente, y el asistente termina respondiendo solo con la web."""

import asyncio
import os
import re
from pathlib import Path

from src.conector import catalogo_fuentes, version as V
from src.conector.instrucciones import INSTRUCCIONES

RAIZ = Path(__file__).resolve().parents[2]
VIEJOS = re.compile(r"`(" + "|".join(sorted(V.NOMBRES_MCP, key=len, reverse=True)) + r")`")


def _herramientas():
    os.environ.setdefault("CONECTOR_FIRMA_SECRET", "k" * 48)
    from src.conector.herramientas import Herramientas
    from src.conector.servidor import Configuracion, construir
    srv, _ = construir(Configuracion(url_publica="https://aientika-conector-000000000000.us-east1.run.app"), Herramientas())
    return srv, asyncio.run(srv.list_tools())


def test_ningun_texto_que_lee_claude_nombra_una_herramienta_vieja():
    _, tools = _herramientas()
    textos = {"instrucciones": INSTRUCCIONES, **{f"descripcion de {t.name}": t.description for t in tools},
              "herramientas.py (mensajes)": (RAIZ / "src/conector/herramientas.py").read_text(encoding="utf-8"),
              "catalogo_fuentes.py": (RAIZ / "src/conector/catalogo_fuentes.py").read_text(encoding="utf-8")}
    for k in ("herramientas.py (mensajes)", "catalogo_fuentes.py"):  # solo las cadenas que salen: sin docstrings ni comentarios
        sin_doc = re.sub(r'"""[\s\S]*?"""', "", textos[k])
        sin_doc = re.sub(r"(?m)#.*$", "", sin_doc)
        textos[k] = "\n".join(re.findall(r'"[^"\n]*"', sin_doc))
    viejos = {k: VIEJOS.findall(v) for k, v in textos.items() if VIEJOS.search(v)}
    assert not viejos, viejos
    # control positivo: el detector sí ve un nombre viejo
    assert VIEJOS.search("pedí la `ficha` del fallo")


def test_cada_nombre_mcp_dice_que_es_de_aientika_y_las_de_busqueda_dicen_costa_rica():
    _, tools = _herramientas()
    nombres = [t.name for t in tools]
    assert nombres == list(V.HERRAMIENTAS) and all(n.startswith("aientika_") and len(n) <= 64 for n in nombres)
    por_nombre = {t.name: t for t in tools}
    for interno in ("buscar", "tramites_buscar"):
        n = V.NOMBRES_MCP[interno]
        assert n.endswith("_cr") and por_nombre[n].description.lstrip().split(".")[0].count("Costa Rica") >= 1
    primera = por_nombre[V.NOMBRES_MCP["buscar"]].description.lstrip().split(".")[0]
    for materia in ("familia", "laboral", "penal", "civil", "constitucional"):
        assert materia in primera, materia


def test_el_servidor_y_el_sitio_dan_el_mismo_nombre_de_conector():
    srv, _ = _herramientas()
    assert srv.name == V.NOMBRE_CONECTOR == "Aiéntika: jurisprudencia y trámites de Costa Rica"
    sitio = (RAIZ / "src/conector/sitio/index.html").read_text(encoding="utf-8")
    assert sitio.count(f"Nombre: <b>{V.NOMBRE_CONECTOR}</b>") == 2  # Claude y ChatGPT
    assert "Nombre: Aiéntika;" not in sitio


def test_las_direcciones_del_conector_van_arriba_de_los_pasos():
    #
    sitio = (RAIZ / "src/conector/sitio/index.html").read_text(encoding="utf-8")
    assert sitio.index('id="direccion"') < sitio.index('data-pasos="claude"') < sitio.index('data-pasos="chatgpt"')


def test_el_catalogo_dice_con_que_herramientas_se_consulta_cada_fuente():
    texto = Path(catalogo_fuentes.__file__).read_text(encoding="utf-8")
    assert f"`{V.NOMBRES_MCP['buscar']}`" in texto and f"`{V.NOMBRES_MCP['tramites_buscar']}`" in texto
