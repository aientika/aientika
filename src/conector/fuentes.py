"""Registro de fuentes de Aiéntika: una sola lista, en código, que usan la herramienta `catalogo` y la página pública.

Estados: `activa` (está en Aiéntika y se actualiza), `incorporando` (todavía no se ofrece) y `pendiente` (analizada, sin incorporar). Una fuente
nueva entra acá ANTES de ofrecerse. Para la jurisprudencia del Poder Judicial no se nombra el sistema de consulta: la fuente visible es la base
de Aiéntika y cada fallo trae su enlace oficial.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Fuente:
    """Una fuente: quién la publica, qué agente la usa, dónde está y cómo se comprueba que sigue sirviendo."""

    id: str
    nombre: str
    agente: str  # «juridico» o «tramites»
    publica: str  # la institución que la publica
    url: str  # página oficial (la que se cita)
    contenido: str
    estado: str  # activa | incorporando | pendiente
    frecuencia: str = "semanal"
    control: str = ""  # reservado para controles de la fuente (no se usa en este repositorio)


FUENTES = (
    Fuente("pj_jurisprudencia", "Jurisprudencia de las Salas y tribunales", "juridico", "Poder Judicial de Costa Rica",
           "https://www.poder-judicial.go.cr", "Sentencias y resoluciones de las Salas de la Corte y de tribunales", "activa",
           "dos veces al día", "la COBERTURA de la base trae el año en curso"),
    Fuente("tra_votos", "Votos del Tribunal Registral Administrativo", "juridico", "Tribunal Registral Administrativo",
           "https://www.tra.go.cr/consultar-votos", "Votos en alzada sobre propiedad industrial, inmuebles, personas jurídicas",
           "incorporando"),
    Fuente("setena_resoluciones", "Resoluciones de SETENA", "juridico", "Secretaría Técnica Nacional Ambiental",
           "https://www.setena.go.cr/es/Catalogo/Resoluciones", "Resoluciones por año, 2014-2026 (carpeta pública)", "pendiente"),
    Fuente("meic_tramites", "Catálogo Nacional de Trámites", "tramites", "Ministerio de Economía, Industria y Comercio (MEIC)",
           "https://tramitescr.meic.go.cr", "Trámites de ministerios, instituciones y municipalidades (Ley 8220): requisitos, costo, "
           "plazo, vigencia, silencio positivo y fundamento legal", "activa"),
    Fuente("ccss_tramites", "Trámites de la CCSS", "tramites", "Caja Costarricense de Seguro Social", "https://www.ccss.sa.cr/tramites",
           "Trámites y gestiones de asegurados, patronos y pensionados", "pendiente"),
)


def por_id(id_: str) -> Fuente:
    """La fuente con ese id (KeyError si no existe: una fuente sin registrar no se usa)."""
    for f in FUENTES:
        if f.id == id_:
            return f
    raise KeyError(id_)


def activas(agente: str | None = None) -> list[Fuente]:
    """Las fuentes que Aiéntika ofrece hoy (de un agente, si se pide)."""
    return [f for f in FUENTES if f.estado == "activa" and (agente is None or f.agente == agente)]
