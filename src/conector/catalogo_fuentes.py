"""El catálogo de lo que Aiéntika tiene, fuente por fuente y con la fecha más actualizada de cada una, para que ante la consulta
de un usuario pueda desplegar la información de que dispone. Lo arma la herramienta `catalogo`; las cifras y fechas salen de los datos cargados, nunca escritas a mano.

Una fuente cuyo dato no se pudo leer dice «NO DISPONIBLE ahora», nunca cero. La jurisprudencia se presenta como «base de Aiéntika»; no se nombra el sistema de consulta.
"""

from __future__ import annotations

from src.conector import fuentes

NO_DISPONIBLE = "NO DISPONIBLE ahora (no es una fuente vacía)"


def _miles(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def ficha_jurisprudencia(f: fuentes.Fuente, cob: dict | None) -> dict:
    """Ficha de la jurisprudencia a partir de la cobertura medida en la base (`cobertura.medir`)."""
    base = {"fuente": f.nombre, "publica": f.publica, "contiene": f.contenido, "enlace_oficial": f.url, "se_actualiza": f.frecuencia,
            "consulta_con": "`aientika_buscar_jurisprudencia_cr`, `aientika_ficha_de_fallo` y `aientika_verificar_cita_de_fallo`"}
    if cob is None:
        return {**base, "cantidad": NO_DISPONIBLE, "periodo": NO_DISPONIBLE, "actualizado_al": NO_DISPONIBLE,
                "mas_reciente": NO_DISPONIBLE}
    annos = cob["annos_cargados"]
    return {**base, "cantidad": f"{_miles(sum(cob['documentos_por_anno'].values()))} resoluciones",
            "periodo": f"{min(annos)}-{max(annos)}", "actualizado_al": cob["datos_cargados_al"],
            "mas_reciente": f"resolución con fecha {cob['fallos_hasta']}" if cob.get("fallos_hasta") else "sin fecha"}


def ficha_tramites(f: fuentes.Fuente, res: dict | None) -> dict:
    """Ficha del catálogo de trámites a partir de `tramites.resumen`."""
    base = {"fuente": f.nombre, "publica": f.publica, "contiene": f.contenido, "enlace_oficial": f.url, "se_actualiza": f.frecuencia,
            "consulta_con": "`aientika_buscar_tramites_cr` y `aientika_ficha_de_tramite`"}
    if res is None:
        return {**base, "cantidad": NO_DISPONIBLE, "periodo": NO_DISPONIBLE, "actualizado_al": NO_DISPONIBLE,
                "mas_reciente": NO_DISPONIBLE}
    return {**base, "cantidad": f"{_miles(res['tramites'])} trámites de {res['instituciones']} instituciones",
            "periodo": "vigentes en el catálogo", "actualizado_al": res["actualizado"],
            "mas_reciente": f"fichas consultadas el {res['actualizado']}"}


def tabla_despachos(despachos: list[dict]) -> str:
    """Tabla en Markdown de la jurisprudencia por Sala y tribunal, con la fecha de la primera y de la más reciente."""
    filas = ["| Sala o tribunal | Resoluciones | Años | Primera | Más reciente |", "|---|---|---|---|---|"]
    filas += [f"| {d['despacho']} | {_miles(d['resoluciones'])} | {d['annos']} | {d['desde'] or 's. f.'} | {d['hasta'] or 's. f.'} |"
              for d in despachos]
    return "\n".join(filas)


def tabla(fichas: list[dict]) -> str:
    """Tabla en Markdown para mostrarle a la persona tal cual."""
    filas = ["| Fuente | Publica | Contiene | Cantidad | Período | Actualizado al | Se actualiza |", "|---|---|---|---|---|---|---|"]
    filas += [f"| {x['fuente']} | {x['publica']} | {x['contiene']} | {x['cantidad']} | {x['periodo']} | {x['actualizado_al']} | "
              f"{x['se_actualiza']} |" for x in fichas]
    return "\n".join(filas)


def armar(cob: dict | None, res_tramites: dict | None, despachos: list[dict] | None = None) -> dict:
    """El catálogo completo: una ficha por fuente activa, la jurisprudencia por Sala y tribunal, las tablas para mostrar y las
    fuentes que se están incorporando.

    `cob` es la cobertura de la jurisprudencia, `res_tramites` el resumen de trámites y `despachos` la lista de `cobertura.despachos`;
    None = no se pudo leer ahora (se dice, no se muestra vacío).
    """
    armadores = {"juridico": lambda f: ficha_jurisprudencia(f, cob), "tramites": lambda f: ficha_tramites(f, res_tramites)}
    activas = [armadores[f.agente](f) for f in fuentes.activas()]
    en_camino = [{"fuente": f.nombre, "publica": f.publica, "contiene": f.contenido, "enlace_oficial": f.url}
                 for f in fuentes.FUENTES if f.estado == "incorporando"]
    salida = {"fuentes": activas, "tabla": tabla(activas), "en_incorporacion": en_camino}
    if despachos is None:
        salida["jurisprudencia_por_despacho"] = NO_DISPONIBLE
    else:
        salida["jurisprudencia_por_despacho"] = despachos
        salida["tabla_jurisprudencia"] = tabla_despachos(despachos)
    salida["como_mostrarlo"] = (
        "Mostrale a la persona la `tabla` tal cual (una fila por fuente, con su fecha de actualización); si pregunta por la "
        "jurisprudencia, también la `tabla_jurisprudencia` (cada Sala y tribunal, con la fecha de su primera resolución y de la más "
        "reciente). Debajo, las fuentes `en_incorporacion`, aclarando que todavía no se pueden consultar. Si un despacho tiene su "
        "resolución más reciente lejos de la fecha de actualización, decilo: no está al día en la base. No agregues fuentes, "
        "despachos ni fechas que no estén acá.")
    return salida
