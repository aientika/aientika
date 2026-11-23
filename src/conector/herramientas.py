"""Lógica de las herramientas del conector, separada del protocolo MCP para probarla sin red.

Cada llamada pasa por el mismo embudo (`_correr`): horario (`limites.SERVICIO_24_HORAS`) → cupo contado ANTES de ejecutar →
ejecución en un hilo (pg8000 es síncrono) → registro de la llamada, y del texto solo con el aviso v2 aceptado (`consulta=`; va a la
tabla `conector_consulta`, nunca a los logs). Todo fallo se traduce a palabras (`_problema`): un error de la base o de Voyage
jamás vuelve como «cero resultados». La unidad se devuelve SOLO si el fallo es del servicio y todavía no se tocó Voyage: un error
de la entrada la gasta (así una ráfaga de entradas inválidas topa igual) y, una vez llamado Voyage, nunca se devuelve (devolverla
permitiría llamar a Voyage sin cupo). En los logs va el NOMBRE del tipo de error, nunca su texto (el error de `tsquery` de
Postgres repite la consulta) ni el argumento recibido, y ninguna excepción sube al SDK, que la registraría con su traceback.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

from src.conector import bd, catalogo_fuentes, limites, presupuesto_voyage, referencia_visita, registro, tarjeta_sitio, tramites
from src.conector.anonimizar import AVISO as AVISO_ANONIMIZACION, AVISO_POR_PERSONA, anonimizar, queda_tema
from src.conector.buscar import buscar as buscar_nucleo, validar_entrada
from src.conector.cobertura import cobertura, despachos as cobertura_despachos
from src.conector.ficha import DocumentoNoEncontrado, ficha as ficha_nucleo
from src.conector.verificar import MAX_FRASE, MIN_FRASE, verificar_cita as verificar_nucleo
from src.conector.version import CONECTOR_VERSION, CONSTRUIDO_POR, NOMBRE_PRODUCTO
from src.conector.voyage_consulta import PresupuestoNoInyectado
from src.indice.embeber_voyage import ErrorVoyage
from src.indice.tope_voyage import SinOptOut

logger = logging.getLogger(__name__)
USUARIO = "usuario"  # el error es de la entrada: la unidad NO se devuelve, el mensaje del núcleo se muestra tal cual
SERVICIO = "servicio"  # el error es nuestro (BD, Voyage): la unidad se devuelve (salvo que ya se llamó a Voyage), con palabras fijas
MAX_ID, MAX_DESPACHO, MAX_TEXTO_REPORTE = 100, 200, 4000  # topes de la frontera: el contrato (la huella) no los declara
# Fallos del embebido tras los cuales `buscar` sigue por la vía literal y lo declara, en vez de no responder nada.
_SIN_SEMANTICA = (ErrorVoyage, SinOptOut, KeyError, PresupuestoNoInyectado, presupuesto_voyage.PresupuestoAgotado, bd.BDNoDisponible)
AVISO_SOLO_LITERAL = {
    "presupuesto_agotado": "La búsqueda por significado no está disponible: se agotó el presupuesto mensual (se renueva el día 1, UTC). "
                           "Estos resultados son solo literales (por palabras): puede haber fallos relevantes que no usan esos términos.",
    "embebido_no_disponible": "La búsqueda por significado no está disponible ahora (el servicio de embebido no respondió). Estos "
                              "resultados son solo literales (por palabras): puede haber fallos relevantes que no usan esos términos.",
    "base_no_disponible": "La búsqueda por significado no está disponible ahora. Estos resultados son solo literales (por palabras): "
                          "puede haber fallos relevantes que no usan esos términos.",
}
COMO_CITAR = ("Citá con el enlace oficial que trae cada fallo; como fuente, «base de Aiéntika (datos al <fecha>)». Antes de reproducir una frase textual, verificala con "
              "`verificar_cita(id, frase)`: dice si está literal y en qué parte del fallo cae (dispositiva, considerandos sin "
              "clasificar, alegato, voto salvado o nota). El conector no afirma que algo sea criterio de la Sala: eso se decide "
              "leyendo el fallo. Este conector no devuelve el texto íntegro: para leer el fallo completo, abrí el enlace.")


def _utc() -> datetime:
    return datetime.now(timezone.utc)


def _problema(exc: Exception) -> tuple[str, str, str]:
    """(tipo de error, quién lo causó, mensaje en palabras). Los mensajes de los errores del servicio son fijos, nunca `str(exc)`."""
    if isinstance(exc, tramites.TramiteNoEncontrado):
        return "no_encontrado", USUARIO, "No hay un trámite con ese id en el catálogo. Usá un id que haya devuelto `aientika_buscar_tramites_cr`."
    if isinstance(exc, tramites.CatalogoNoDisponible):
        return "catalogo_no_disponible", SERVICIO, ("El catálogo de trámites no está disponible ahora. No es que no haya trámites: "
                                                    "no se pudo consultar. Probá de nuevo más tarde.")
    if isinstance(exc, DocumentoNoEncontrado):
        return "no_encontrado", USUARIO, "No hay un fallo con ese id en la base. Usá un id que haya devuelto `aientika_buscar_jurisprudencia_cr`."
    if isinstance(exc, ValueError):
        return "entrada_invalida", USUARIO, str(exc)[:240]
    if isinstance(exc, bd.BDNoDisponible):
        return "base_no_disponible", SERVICIO, ("La base de jurisprudencia no respondió. No es que no haya resultados: no se pudo "
                                                "consultar. Probá de nuevo en unos minutos.")
    if isinstance(exc, presupuesto_voyage.PresupuestoAgotado):
        return "presupuesto_agotado", SERVICIO, ("Se agotó el presupuesto mensual de la búsqueda por significado. No es que no haya "
                                                 "resultados: la búsqueda no se hizo. Se renueva el primer día del mes (UTC).")
    if isinstance(exc, (ErrorVoyage, SinOptOut, KeyError)):
        return "embebido_no_disponible", SERVICIO, ("No se pudo preparar la búsqueda por significado. No es que no haya resultados: "
                                                    "la búsqueda no se hizo. Probá de nuevo en unos minutos.")
    return "error_interno", SERVICIO, "Falló la consulta por un error del servicio. No es que no haya resultados. Probá de nuevo."


def _acotar(nombre: str, valor: str, maximo: int) -> None:
    """ValueError (error de la entrada) si `valor` pasa de `maximo` caracteres."""
    if len(valor) > maximo:
        raise ValueError(f"`{nombre}` pasa de {maximo} caracteres")


class Herramientas:
    """Las herramientas. `embeber(consulta) -> vector` y `reloj()` se inyectan; `embeber=None` solo en desarrollo (búsqueda literal)."""

    def __init__(self, embeber=None, reloj=_utc):
        self.embeber, self.reloj = embeber, reloj

    async def _correr(self, nombre: str, invitado: str, cliente: str | None, trabajo, cuenta: bool = True,
                      consulta: tuple | None = None) -> dict:
        """El embudo común. `trabajo()` es síncrono y devuelve el dict de la respuesta. `consulta` = (aviso_version, texto, filtros):
        se guarda junto a la fila de la llamada, sea cual sea el resultado, solo si `registro.guarda_texto(aviso_version)`."""
        t0, ahora = time.monotonic(), self.reloj()
        if limites.fuera_de_horario(ahora):
            return {"error": "fuera_de_horario", "mensaje": limites.MENSAJE_FUERA_DE_HORARIO}
        cupo = None
        if cuenta:
            try:
                veredicto = await asyncio.to_thread(limites.consumir, nombre, invitado, ahora)
            except Exception as exc:
                return await self._fallo(nombre, invitado, cliente, t0, exc, devolver=False, consulta=consulta)
            if not veredicto.permitido:
                await self._anotar(nombre, invitado, cliente, t0, "limite", consulta=consulta)
                return {"error": "limite_alcanzado", "mensaje": veredicto.mensaje}
            cupo = veredicto.cupo
        try:
            salida = await asyncio.to_thread(trabajo)
        except Exception as exc:
            return await self._fallo(nombre, invitado, cliente, t0, exc, devolver=cuenta, consulta=consulta)
        await self._anotar(nombre, invitado, cliente, t0, "ok", salida.get("total"), salida.get("via"), consulta=consulta)
        return {**salida, "cupo": cupo} if cupo else salida

    async def _fallo(self, nombre, invitado, cliente, t0, exc, devolver: bool, consulta: tuple | None = None) -> dict:
        tipo, quien, mensaje = _problema(exc)
        logger.error("[conector] falló %s: %s", nombre, type(exc).__name__)  # solo el tipo, nunca el texto
        # La unidad se contó antes de ejecutar. Se devuelve solo si el fallo es nuestro Y no se llegó a Voyage (que reserva y cobra).
        if devolver and quien == SERVICIO and not getattr(exc, "voyage_intentado", False):
            try:
                await asyncio.to_thread(limites.devolver, nombre, invitado, self.reloj())
            except Exception as exc2:
                logger.warning("[conector] no se pudo devolver la unidad de %s: %s", nombre, type(exc2).__name__)
        await self._anotar(nombre, invitado, cliente, t0, f"error:{tipo}", consulta=consulta)
        return {"error": tipo, "quien": quien, "mensaje": mensaje}

    async def _anotar(self, nombre, invitado, cliente, t0, resultado, n=None, via=None, consulta: tuple | None = None) -> None:
        await asyncio.to_thread(self._registrar, int(self.reloj().timestamp()), invitado, nombre, resultado,
                                int((time.monotonic() - t0) * 1000), n, via, cliente, consulta)

    @staticmethod
    def _registrar(ts, invitado, nombre, resultado, duracion_ms, n, via, cliente, consulta) -> None:
        """La fila de la llamada y, si la credencial aceptó el aviso v2, la del texto. Ninguna de las dos propaga errores."""
        registro.registrar(ts, invitado, nombre, resultado, duracion_ms, n, via, cliente, CONECTOR_VERSION)
        if consulta is not None and registro.guarda_texto(consulta[0]):
            registro.registrar_consulta(ts, invitado, nombre, consulta[1], consulta[2])

    def no_verificado(self) -> dict:
        """Respuesta para un token que no se pudo cotejar con la base: se dice por qué, sin tocar datos ni contar cupo."""
        if limites.fuera_de_horario(self.reloj()):
            return {"error": "fuera_de_horario", "mensaje": limites.MENSAJE_FUERA_DE_HORARIO}
        _, _, mensaje = _problema(bd.BDNoDisponible("credencial sin verificar"))
        return {"error": "base_no_disponible", "quien": SERVICIO, "mensaje": mensaje}

    # --- las herramientas -------------------------------------------------------------------------------------------------

    async def buscar(self, invitado, cliente, consulta, despacho=None, anno=None, desde=None, hasta=None, *,
                     aviso_version: int | None = None) -> dict:
        """Busca fallos. Cuesta una unidad de cupo; el vector de la consulta sale de Voyage con su presupuesto propio."""
        consulta, omitidos = anonimizar(consulta)  # antes de Voyage, de la base y del registro: se busca por el tema, no por personas
        if omitidos and not queda_tema(consulta):  # era una búsqueda por persona: no se ejecuta ni gasta cupo
            return {"resultados": [], "busqueda_por_persona": True, "aviso_anonimizacion": AVISO_POR_PERSONA}

        def trabajo():
            validar_entrada(consulta, desde, hasta)  # TODA la entrada, ANTES de Voyage: lo inválido no gasta presupuesto
            _acotar("despacho", despacho or "", MAX_DESPACHO)
            vector, motivo, intento = None, None, False
            if self.embeber:
                intento = True
                try:
                    vector = self.embeber(consulta)
                except _SIN_SEMANTICA as exc:  # la vía literal sigue disponible; se degrada DECLARÁNDOLO, nunca en silencio
                    motivo = _problema(exc)[0]
                    logger.warning("[conector] buscar sin búsqueda por significado: %s", type(exc).__name__)  # solo el tipo, nunca el texto
            try:
                conn = bd.conectar_lectura()
                try:
                    r = buscar_nucleo(conn, consulta, despacho, anno, desde, hasta, vector)
                finally:
                    conn.close()
            except Exception as exc:
                exc.voyage_intentado = intento  # ya se reservó/gastó en Voyage: la unidad no vuelve
                raise
            via = "semantica+literal" if r["semantica_usada"] else "literal"
            if motivo:
                aviso = AVISO_SOLO_LITERAL.get(motivo, AVISO_SOLO_LITERAL["embebido_no_disponible"])
                r["semantica_no_disponible"] = motivo
                r["aviso"] = " ".join(x for x in (aviso, r.get("aviso")) if x)
            if omitidos:
                r["aviso_anonimizacion"] = AVISO_ANONIMIZACION.format(n=omitidos)
            cob = r.pop("cobertura")
            ref = referencia_visita.crear(invitado, int(self.reloj().timestamp())) if referencia_visita.corresponde(aviso_version) else None
            return {"cobertura": cob, "fuente": tarjeta_sitio.linea_fuente(cob, cliente, ref),
                    "fuente_instruccion": "Cerrá la respuesta con la línea `fuente` tal cual, con el enlace markdown [aientika.ai](...) clickeable.", "via": via, **r}
        filtros = {"despacho": despacho, "anno": anno, "desde": desde, "hasta": hasta}
        return await self._correr("buscar", invitado, cliente, trabajo, consulta=(aviso_version, consulta, filtros))

    async def ficha(self, invitado, cliente, id, *, aviso_version: int | None = None) -> dict:
        """Encabezado, «por tanto» de mayoría, disidencias y enlace de un fallo."""
        def trabajo():
            _acotar("id", id, MAX_ID)
            return self._leer(lambda c: ficha_nucleo(c, id))
        return await self._correr("ficha", invitado, cliente, trabajo, consulta=(aviso_version, id, None))

    async def verificar_cita(self, invitado, cliente, id, frase, *, aviso_version: int | None = None) -> dict:
        """Veredicto de una frase contra el fallo `id`: solo el veredicto, nunca el texto de alrededor."""
        def trabajo():
            _acotar("id", id, MAX_ID)
            _acotar("frase", frase, 4 * MAX_FRASE)  # antes de normalizarla entera solo para rechazarla por larga
            return self._leer(lambda c: verificar_nucleo(c, id, frase))
        return await self._correr("verificar_cita", invitado, cliente, trabajo, consulta=(aviso_version, frase, {"id": id}))

    def _leer(self, fn):
        conn = bd.conectar_lectura()
        try:
            return fn(conn)
        finally:
            conn.close()

    async def ayuda(self, invitado, cliente) -> dict:
        """Cómo se usa, la cobertura y el cupo con la hora de renovación. No gasta cupo de búsqueda (tiene su tope diario); sin base, devuelve lo fijo y lo dice."""
        def trabajo():
            salida = {"conector": f"{NOMBRE_PRODUCTO}: base propia de jurisprudencia de Costa Rica (cada fallo trae su enlace oficial)", "version_conector": CONECTOR_VERSION,
                      "construido_por": CONSTRUIDO_POR,
                      "horario": limites.HORARIO_LEGIBLE, "como_citar": COMO_CITAR,
                      "herramientas": {"buscar": "busca fallos; gasta 1 unidad de cupo", "ficha": "encabezado y «por tanto» de un fallo",
                                       "verificar_cita": f"¿esta frase (mínimo {MIN_FRASE} caracteres) está literal en el fallo, y dónde?",
                                       "tramites_buscar": "busca trámites del Estado (requisitos, costo, plazo); gasta 1 unidad del mismo cupo",
                                       "tramite": "ficha completa de un trámite con su fuente oficial",
                                       "catalogo": "qué fuentes tiene Aiéntika y a qué fecha",
                                       "reportar": "avisa que una respuesta no sirvió"}}
            try:
                salida["cobertura"] = self._leer(lambda c: cobertura(c)["linea"])
                salida["cupo"] = limites.resumen(invitado, self.reloj())
            except bd.BDNoDisponible:
                salida["cobertura"] = "NO DISPONIBLE ahora: la base no respondió. No es una cobertura vacía."
            return salida
        return await self._correr("ayuda", invitado, cliente, trabajo)

    async def reportar(self, invitado, cliente, resumen, problema) -> dict:
        """Guarda un reporte voluntario de Claude. No incluir el texto de la consulta (lo dice la descripción de la herramienta)."""
        def trabajo():
            if not resumen.strip() or not problema.strip():
                raise ValueError("`resumen` y `problema` no pueden ir vacíos")
            _acotar("resumen", resumen, MAX_TEXTO_REPORTE)
            _acotar("problema", problema, MAX_TEXTO_REPORTE)
            registro.registrar_reporte(int(self.reloj().timestamp()), invitado, CONECTOR_VERSION, resumen, problema)
            return {"estado": "recibido", "mensaje": "Reporte recibido. Gracias: avisale a la persona en una línea que lo reportaste."}
        return await self._correr("reportar", invitado, cliente, trabajo)

    # --- Trámites -----------------------------------------------------------

    async def tramites_buscar(self, invitado, cliente, consulta, institucion=None, *, aviso_version: int | None = None) -> dict:
        """Busca trámites en el catálogo del MEIC. Gasta una unidad del MISMO cupo que `buscar`."""
        consulta, omitidos = anonimizar(consulta)  # tampoco se busca trámites por personas ni queda un dato personal en el registro
        if omitidos and not queda_tema(consulta):
            return {"resultados": [], "busqueda_por_persona": True, "aviso_anonimizacion": AVISO_POR_PERSONA}

        def trabajo():
            _acotar("consulta", consulta, 500)
            _acotar("institucion", institucion or "", MAX_DESPACHO)
            r = tramites.buscar(consulta, institucion)
            if omitidos:
                r["aviso_anonimizacion"] = AVISO_ANONIMIZACION.format(n=omitidos)
            return r
        return await self._correr("tramites_buscar", invitado, cliente, trabajo,
                                  consulta=(aviso_version, consulta, {"institucion": institucion}))

    async def tramite(self, invitado, cliente, id) -> dict:
        """La ficha completa de un trámite con su fuente. Sin costo de cupo (los datos están en la imagen)."""
        def trabajo():
            _acotar("id", str(id), MAX_ID)
            return tramites.ficha(id)
        return await self._correr("tramite", invitado, cliente, trabajo)

    async def visitar_sitio(self, invitado, cliente) -> dict:
        """Prueba de tarjeta visual: el enlace a aientika.ai con la marca de origen (tarjeta_sitio). Sin costo de cupo."""
        return await self._correr("visitar_sitio", invitado, cliente, lambda: tarjeta_sitio.resultado(cliente))

    async def catalogo(self, invitado, cliente) -> dict:
        """Qué tiene Aiéntika: el registro de fuentes con su estado y, de las activas, cuánto cubren. Sin costo."""
        def trabajo():
            try:
                cob, despachos = self._leer(lambda c: (cobertura(c), cobertura_despachos(c)))
            except bd.BDNoDisponible:
                cob, despachos = None, None
            try:
                res = tramites.resumen()
            except tramites.CatalogoNoDisponible:
                res = None
            return {"conector": NOMBRE_PRODUCTO, **catalogo_fuentes.armar(cob, res, despachos)}
        return await self._correr("catalogo", invitado, cliente, trabajo)
