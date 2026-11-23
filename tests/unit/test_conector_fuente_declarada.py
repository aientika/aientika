"""Lo que Claude lee no nombra otro sistema de consulta como fuente ni como origen de los datos.

Aiéntika busca en su propia base. La única forma admitida de la fuente es «base de Aiéntika (datos al <fecha>)». Cada fallo lleva su enlace
oficial, y el dominio de ese enlace es lo único que puede decir «nexuspj».

Control: se revisa TODO lo que Claude lee: las instrucciones del `initialize`, la descripción de cada herramienta, la línea
COBERTURA, `COMO_CITAR` y la salida de `ayuda`.
"""

import asyncio
import os

from src.conector import herramientas as H
from src.conector.cobertura import linea
from src.conector.instrucciones import INSTRUCCIONES
from src.conector.servidor import Configuracion, construir

URL = "https://aientika-conector-0.us-east1.run.app"
COBERTURA = {"annos_cargados": [2024, 2025, 2026], "semantica": {2026: {"fraccion": 1.0, "tribunales": False}},
             "datos_cargados_al": "2026-11-10"}


def _textos_que_lee_claude() -> dict[str, str]:
    os.environ.setdefault("CONECTOR_FIRMA_SECRET", "k" * 48)
    srv, _ = construir(Configuracion(url_publica=URL), H.Herramientas())
    textos = {"instrucciones": INSTRUCCIONES, "cobertura": linea(COBERTURA), "como_citar": H.COMO_CITAR}
    textos.update({f"herramienta:{t.name}": t.description or "" for t in asyncio.run(srv.list_tools())})
    fuente = open(H.__file__, encoding="utf-8").read()
    inicio = fuente.index('salida = {"conector": ')
    textos["ayuda:conector"] = fuente[inicio:fuente.index("\n", inicio)]
    return textos


def test_nada_de_lo_que_lee_claude_nombra_a_nexus():
    textos = _textos_que_lee_claude()
    assert len(textos) >= 8  # precondición: instrucciones, cobertura, cómo citar, ayuda y las 5 herramientas
    con_nexus = {k: v for k, v in textos.items() if "nexus" in v.lower()}
    assert con_nexus == {}, f"nombran a Nexus: {sorted(con_nexus)}"


def test_la_fuente_se_declara_como_base_de_agentika_con_fecha():
    # la línea de fuente invita a visitar el sitio (la tarjeta `visitar_sitio` puede no llamarse).
    assert "«Fuente: base de Aiéntika (datos al <fecha de la COBERTURA>) · Conocé más en aientika.ai»" in INSTRUCCIONES
    assert "ni escribas «vía Aiéntika»" in INSTRUCCIONES
    assert "en la base de Aiéntika" in linea(COBERTURA)
    assert "base de Aiéntika (datos al <fecha>)" in H.COMO_CITAR


def test_control_positivo_el_detector_ve_a_nexus_si_vuelve():
    textos = _textos_que_lee_claude()
    textos["instrucciones"] = INSTRUCCIONES + " Fuente: Nexus PJ."
    assert {k for k, v in textos.items() if "nexus" in v.lower()} == {"instrucciones"}
