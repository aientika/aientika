"""Versión del CONTRATO del conector: qué herramientas hay, con qué parámetros y qué anotaciones. Historia en
`docs/architecture/conector_changelog.md`.

`CONECTOR_VERSION` sube cuando cambia ese contrato, no con cada deploy. `HUELLAS` guarda la huella del contrato de cada versión
publicada: el test calcula la huella de las herramientas reales y falla si no coincide con la de `CONECTOR_VERSION`, es decir, si se
agregó, quitó o cambió un parámetro sin subir la versión (mismo principio que los contratos versionados).
Una versión ya publicada no se edita: la nueva se agrega y se sube `CONECTOR_VERSION`.
"""

from __future__ import annotations

import hashlib
import json

CONECTOR_VERSION = "2.1.1"
# Nombre que ven el colega y su Claude.
NOMBRE_PRODUCTO = "Aiéntika"
# Nombre que el servidor le declara a Claude en el `initialize` y que el sitio le indica al colega al instalar. Con «Aiéntika» a
# secas, Claude no lo consultaba para preguntas jurídicas de otras materias. Las
# pantallas y la línea de fuente siguen con NOMBRE_PRODUCTO.
NOMBRE_CONECTOR = "Aiéntika: jurisprudencia y trámites de Costa Rica"
AUTOR = "Andrés y Alejandro"
SITIO_AUTOR = "https://alejoherrera.com"
CONSTRUIDO_POR = f"Construido por {AUTOR} · alejoherrera.com"
# El conector declara quién lo construyó (ver `CONSTRUIDO_POR`).
# Nombre MCP de cada herramienta (contrato 2.0.0). La clave es el nombre interno, que siguen usando los cupos (`limites`) y el
# registro (`conector_llamada.herramienta`); el valor es lo que ve Claude. Los nombres de 1.x (`buscar`, `ficha`…) no decían
# de qué país ni de qué materia eran y Claude no los encontraba entre las herramientas diferidas.
NOMBRES_MCP = {
    "buscar": "aientika_buscar_jurisprudencia_cr",
    "ficha": "aientika_ficha_de_fallo",
    "verificar_cita": "aientika_verificar_cita_de_fallo",
    "ayuda": "aientika_ayuda",
    "tramites_buscar": "aientika_buscar_tramites_cr",
    "tramite": "aientika_ficha_de_tramite",
    "catalogo": "aientika_catalogo_de_fuentes",
    "visitar_sitio": "aientika_visitar_sitio",
    "reportar": "aientika_reportar_respuesta",
}
HERRAMIENTAS = tuple(NOMBRES_MCP.values())
HUELLAS = {
    "1.0.0": "b86be7068af35219b22ee8fa4bc84b2b8c62b38bec31cc14d15e16bdf9f5d968",
    "1.1.0": "ef3dc32cc0e984c07bee8446baa2a05ac9a32165ac689a10256796a62ca7391e",  # `reportar` deja de ser readOnlyHint
    # 1.2.0: misma entrada (misma huella); cambia la SALIDA de `buscar` (distancia, senal_semantica). Se sube igual para que
    # `registro` y `reportar` distingan lo anterior y lo posterior a la señal.
    "1.2.0": "ef3dc32cc0e984c07bee8446baa2a05ac9a32165ac689a10256796a62ca7391e",
    # 1.3.0: misma entrada (misma huella); cambia la SALIDA de `buscar`, `ficha` y `verificar_cita`: `mayoria` desaparece,
    # rótulos neutros, `citable_como_criterio`, `por_tanto` null con aviso.
    "1.3.0": "ef3dc32cc0e984c07bee8446baa2a05ac9a32165ac689a10256796a62ca7391e",
    # 1.4.0: misma entrada (misma huella); en los fallos que marca la guarda, `por_tanto` deja de ser null y trae la dispositiva
    # que elige `extracto.por_tanto` con `por_tanto_aviso`.
    "1.4.0": "ef3dc32cc0e984c07bee8446baa2a05ac9a32165ac689a10256796a62ca7391e",
    # 1.5.0: misma entrada; `buscar` y `ficha` agregan `por_tanto_recortado` y cortan la dispositiva por oración, y el
    # registro de uso guarda el texto de las consultas con el aviso v2.
    "1.5.0": "ef3dc32cc0e984c07bee8446baa2a05ac9a32165ac689a10256796a62ca7391e",
    # 1.6.0: Trámites: `tramites_buscar`, `tramite` y `catalogo`.
    "1.6.0": "0c31d5d2c047257311fc82753035c03bed4eb8aa270906267db640099138e88c",
    # 1.7.0: misma entrada (misma huella); `catalogo` cambia la SALIDA: ficha por fuente con cantidad, período y fecha de
    # actualización, la jurisprudencia por Sala y tribunal (primera y más reciente) y las tablas para mostrar.
    "1.7.0": "0c31d5d2c047257311fc82753035c03bed4eb8aa270906267db640099138e88c",
    # 1.8.0: `visitar_sitio` con tarjeta visual (MCP Apps / ChatGPT).
    "1.8.0": "9d966eb7eee9cdce5be2c8ad6c1fff38440ccba16c122d6adb09237e96135fbe",
    # 1.9.0: misma entrada (misma huella); `buscar` cambia la SALIDA: trae `fuente` (la línea lista para copiar, con el enlace al
    # sitio) y `fuente_instruccion`, porque Claude y ChatGPT no remitían al sitio con la instrucción sola.
    "1.9.0": "9d966eb7eee9cdce5be2c8ad6c1fff38440ccba16c122d6adb09237e96135fbe",
    # 1.10.0: misma entrada; `fuente` trae el enlace al sitio en markdown.
    "1.10.0": "9d966eb7eee9cdce5be2c8ad6c1fff38440ccba16c122d6adb09237e96135fbe",
    # 1.11.0: misma entrada; la marca pasa a «Aiéntika»: `fuente` dice «base de Aiéntika».
    "1.11.0": "9d966eb7eee9cdce5be2c8ad6c1fff38440ccba16c122d6adb09237e96135fbe",
    # 1.12.0: misma entrada; con el aviso v3 el enlace de `fuente` lleva la referencia cifrada de la visita.
    "1.12.0": "9d966eb7eee9cdce5be2c8ad6c1fff38440ccba16c122d6adb09237e96135fbe",
    # 1.13.0: misma entrada; `fuente` y la tarjeta llevan a aientika.ai (sitio propio); la
    # referencia de la visita exige el aviso v4.
    "1.13.0": "9d966eb7eee9cdce5be2c8ad6c1fff38440ccba16c122d6adb09237e96135fbe",
    # 1.14.0: misma entrada; cambia el horario de servicio de la base de datos.
    "1.14.0": "9d966eb7eee9cdce5be2c8ad6c1fff38440ccba16c122d6adb09237e96135fbe",
    # 2.0.0: los nombres MCP pasan a `aientika_*` con país y contenido (`aientika_buscar_jurisprudencia_cr`…): Claude no encontraba
    # `buscar` entre las herramientas diferidas. Rompe a los clientes que llamen los
    # nombres viejos hasta que reconecten; mismos parámetros y anotaciones.
    "2.0.0": "f821c979928e2065938ab565cdd576a328f96e3a57c338c55ef0017f5655b065",
    # 2.1.0: misma entrada; la línea COBERTURA separa Salas y tribunales por año (decía «Salas y tribunales» en años en que los
    # tribunales no tenían vectores).
    "2.1.0": "f821c979928e2065938ab565cdd576a328f96e3a57c338c55ef0017f5655b065",
    # 2.1.1: misma entrada; las instrucciones prohiben ofrecer vias procesales de memoria y la ficha usa el extracto parchado.
    "2.1.1": "f821c979928e2065938ab565cdd576a328f96e3a57c338c55ef0017f5655b065",
}


def huella_contrato(herramientas) -> str:
    """sha256 de nombre, esquema de entrada y anotaciones de cada herramienta (sin las descripciones: afinar un texto no es otro contrato)."""
    filas = sorted((t.name, t.inputSchema, t.annotations.model_dump(exclude_none=True) if t.annotations else None)
                   for t in herramientas)
    return hashlib.sha256(json.dumps(filas, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
