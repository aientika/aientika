"""Registro de uso del conector: cada llamada en `conector_llamada` (sin texto) y, con el aviso v2, el texto en `conector_consulta`.

`conector_llamada` guarda quién (id de invitado, un seudónimo al azar), qué herramienta, el resultado en una palabra, duración, número de
resultados y vía. `conector_consulta` guarda el texto de la consulta, la frase o el id
del fallo SOLO si la credencial aceptó el aviso v2 (`AVISO_MINIMO_TEXTO`): las credenciales anteriores se emitieron con la promesa
«no se guarda el texto de tus consultas» y la conservan. Cada inserción borra lo que pasó de `DIAS_RETENCION_CONSULTAS`.

Registrar NUNCA voltea una llamada: si la base falla se pierde una fila de contabilidad, no una respuesta. Pero
puede subcontar en silencio: por eso el fallo deja un `warning` con SOLO el nombre del tipo de error —jamás su texto, que
en un error de `tsquery` o de un INSERT repite la consulta—. Ese aviso conviene vigilarlo si el registro se usa para
medir. El texto de una consulta no pasa por los logs: vive en la tabla y en ningún otro lado.
"""

from __future__ import annotations

import json
import logging

from src.conector import bd
from src.conector.anonimizar import anonimizar

logger = logging.getLogger(__name__)
TOPE_CAMPO = 60
TOPE_TEXTO = 8000  # el tope de `frase` en la frontera (herramientas: 4 * MAX_FRASE); `consulta` ya llega acotada a 2.000
AVISO_MINIMO_TEXTO = 2  # desde esta versión del aviso de privacidad el invitado sabe que el texto se guarda
DIAS_RETENCION_CONSULTAS = 90


def registrar(ts: int, invitado: str | None, herramienta: str, resultado: str, duracion_ms: int | None = None,
              n_resultados: int | None = None, via: str | None = None, cliente: str | None = None,
              version: str | None = None) -> None:
    """Anota una llamada. No propaga errores; los campos son cortos y ninguno es texto libre del usuario."""
    try:
        with bd.estado() as conn:
            conn.cursor().execute(
                "INSERT INTO conector_llamada (ts, invitado_id, herramienta, resultado, duracion_ms, n_resultados, via, cliente, "
                "version) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (ts, invitado, herramienta[:TOPE_CAMPO], resultado[:TOPE_CAMPO], duracion_ms, n_resultados,
                 via and via[:TOPE_CAMPO], cliente and cliente[:120], version))
    except Exception as exc:  # deliberado: la consulta del usuario vale más que su fila de contabilidad
        logger.warning("[conector-registro] no se pudo anotar la llamada %s: %s", herramienta, type(exc).__name__)


def guarda_texto(aviso_version: int | None) -> bool:
    """¿La credencial aceptó un aviso que dice que el texto se guarda? None (credencial anterior) o 1: no."""
    return aviso_version is not None and aviso_version >= AVISO_MINIMO_TEXTO


def registrar_consulta(ts: int, invitado: str | None, herramienta: str, texto: str, filtros: dict | None = None) -> None:
    """Guarda el texto de una consulta y, en la MISMA transacción, borra lo anterior a `DIAS_RETENCION_CONSULTAS`.

    El que llama decide si corresponde (`guarda_texto`). No propaga errores, y el aviso lleva solo el NOMBRE del tipo de error: el
    texto de la excepción de un INSERT puede traer el parámetro, es decir, la consulta.
    """
    try:
        limpios = {k: v for k, v in (filtros or {}).items() if v is not None}
        with bd.estado() as conn:
            cur = conn.cursor()
            cur.execute("INSERT INTO conector_consulta (ts, invitado_id, herramienta, texto, filtros) VALUES (%s, %s, %s, %s, %s)",
                        (ts, invitado, herramienta[:TOPE_CAMPO], anonimizar(str(texto))[0][:TOPE_TEXTO],
                         json.dumps(limpios, ensure_ascii=False) if limpios else None))
            cur.execute("DELETE FROM conector_consulta WHERE ts < %s", (ts - DIAS_RETENCION_CONSULTAS * 86400,))
    except Exception as exc:  # deliberado: como en `registrar`, la respuesta vale más que su registro
        logger.warning("[conector-registro] no se pudo anotar la consulta de %s: %s", herramienta, type(exc).__name__)


def registrar_reporte(ts: int, invitado: str | None, version: str, resumen: str, problema: str) -> None:
    """Guarda un reporte voluntario de Claude (`reportar`). Sí propaga el error: el reporte ES la operación, no su contabilidad."""
    with bd.estado() as conn:
        conn.cursor().execute(
            "INSERT INTO conector_reporte (ts, invitado_id, version, resumen, problema) VALUES (%s, %s, %s, %s, %s)",
            (ts, invitado, version, resumen[:500], problema[:1000]))
