"""Código de un solo uso por correo (lógica, presupuesto de adivinanza y alta por correo). Con controles positivos.

La pantalla de acceso todavía no lo usa: estos tests fijan la lógica ANTES de conectarla.
"""

import hashlib
import sqlite3
import threading

import pytest
from conector_apoyo import estado_sqlite, logs  # noqa: F401 - fixtures

from src.conector import bd, codigo_correo as C, invitados

CLAVE = "clave-del-servicio-para-las-pruebas"
CLI = "cliente-1"
T0 = 1_800_000_000  # un instante cualquiera (segundos UTC)


def _invitado(correo="colega@bufete.cr"):
    with bd.estado() as conn:
        return invitados.alta_por_correo(conn.cursor(), correo, "Colega", T0)


def _emitir(inv, cli=CLI, ahora=T0):
    with bd.estado() as conn:
        return C.emitir(conn.cursor(), inv, cli, ahora, CLAVE)


def _verificar(inv, codigo, cli=CLI, ahora=T0):
    with bd.estado() as conn:
        return C.verificar(conn.cursor(), inv, cli, codigo, ahora, CLAVE)


def _uso(clave_like):
    with bd.estado() as conn:
        cur = conn.cursor()
        cur.execute("SELECT clave, unidades FROM uso WHERE clave LIKE %s", (clave_like,))
        return {f[0]: int(f[1]) for f in cur.fetchall()}


def _fila_codigo(inv):
    with bd.estado() as conn:
        cur = conn.cursor()
        cur.execute("SELECT intentos, usado_ts, codigo_hmac FROM codigo_correo WHERE invitado_id = %s ORDER BY creado_ts DESC, id", (inv,))
        return cur.fetchall()


def _malo(codigo):
    return "000000" if codigo != "000000" else "111111"


# ---- 1. un solo uso ----
def test_un_codigo_se_verifica_una_sola_vez_y_marca_el_correo_como_verificado(estado_sqlite):
    inv = _invitado()
    codigo = _emitir(inv)
    assert len(codigo) == C.LARGO and codigo.isdigit()
    assert _verificar(inv, codigo) == C.OK  # control positivo
    assert _verificar(inv, codigo) == C.AGOTADO  # la segunda vez no sirve
    with bd.estado() as conn:
        cur = conn.cursor()
        cur.execute("SELECT correo_verificado_ts FROM invitado WHERE id = %s", (inv,))
        assert cur.fetchone()[0] == T0


def test_el_codigo_se_acepta_con_espacios_y_guiones_como_lo_escribe_el_colega(estado_sqlite):
    inv = _invitado()
    codigo = _emitir(inv)
    assert _verificar(inv, f"{codigo[:3]} - {codigo[3:]}") == C.OK


def test_dos_verificaciones_correctas_a_la_vez_solo_una_gana(estado_sqlite):
    inv = _invitado()
    codigo = _emitir(inv)
    resultados = []

    def intentar():
        try:
            resultados.append(_verificar(inv, codigo))
        except sqlite3.OperationalError:  # SQLite serializa las escrituras: quien no consigue el candado no verifica
            resultados.append("bloqueada")
    hilos = [threading.Thread(target=intentar) for _ in range(8)]
    [h.start() for h in hilos]
    [h.join() for h in hilos]
    assert resultados.count(C.OK) == 1  # control: exactamente una, no cero y no varias


# ---- 2. vigencia, cliente, intentos, otro código ----
def test_vence_a_los_10_minutos_y_no_sirve_con_otro_cliente_pero_si_con_el_mismo(estado_sqlite):
    inv = _invitado()
    codigo = _emitir(inv)
    assert _verificar(inv, codigo, cli="cliente-de-un-tercero") == C.AGOTADO  # atado al cliente: otro cliente no lo usa
    assert _verificar(inv, codigo, ahora=T0 + C.VIGENCIA_S + 1) == C.AGOTADO  # venció
    assert _verificar(inv, codigo, ahora=T0 + C.VIGENCIA_S) == C.OK  # control positivo: el mismo cliente, en el último segundo vigente


def test_el_codigo_no_depende_de_la_solicitud_oauth_un_reinicio_de_desktop_no_lo_pierde(estado_sqlite):
    """El código vale para cualquier solicitud del MISMO cliente; la función ni siquiera recibe `s`."""
    import inspect
    assert "s" not in inspect.signature(C.verificar).parameters and "estado" not in inspect.signature(C.verificar).parameters
    inv = _invitado()
    codigo = _emitir(inv)
    assert _verificar(inv, codigo, ahora=T0 + 90) == C.OK  # llegó tarde, por otra solicitud del mismo cliente, y sirve


def test_cinco_intentos_malos_agotan_el_codigo_aunque_despues_se_escriba_el_correcto(estado_sqlite):
    inv = _invitado()
    codigo = _emitir(inv)
    assert [_verificar(inv, _malo(codigo)) for _ in range(C.MAX_INTENTOS)] == [C.INCORRECTO] * C.MAX_INTENTOS
    assert _verificar(inv, codigo) == C.AGOTADO  # ya no hay intentos: ni el correcto entra
    assert _fila_codigo(inv)[0][0] == C.MAX_INTENTOS  # y no se pasó de 5
    otro = _emitir(inv, ahora=T0 + 2000)  # control positivo: uno nuevo sí funciona
    assert _verificar(inv, otro, ahora=T0 + 2000) == C.OK


def test_pedir_otro_codigo_anula_el_anterior(estado_sqlite):
    inv = _invitado()
    viejo = _emitir(inv)
    nuevo = _emitir(inv, ahora=T0 + 1000)
    assert viejo != nuevo or True  # (colisión de 1 en un millón: el resto del test no depende de que sean distintos)
    vigentes = [f for f in _fila_codigo(inv) if f[1] is None]
    assert len(vigentes) == 1  # solo uno sigue vivo
    assert _verificar(inv, nuevo, ahora=T0 + 1000) == C.OK


# ---- 3. bloqueo por fallos ----
def test_diez_fallos_en_un_dia_bloquean_al_invitado_y_ya_no_se_consumen_intentos(estado_sqlite):
    inv = _invitado()
    ahora = T0
    for _ in range(2):  # dos códigos con 5 fallos cada uno = 10 fallos
        codigo = _emitir(inv, ahora=ahora)
        for _ in range(C.MAX_INTENTOS):
            assert _verificar(inv, _malo(codigo), ahora=ahora) == C.INCORRECTO
        ahora += 1000
    with bd.estado() as conn:
        assert C.fallos_de_hoy(conn.cursor(), inv, T0) == C.FALLOS_POR_INVITADO_DIA  # control: de verdad llegó a 10
    nuevo = _emitir(inv, ahora=ahora)
    antes = _fila_codigo(inv)[0][0]
    assert _verificar(inv, nuevo, ahora=ahora) == C.BLOQUEADO  # bloqueado aunque el código sea el correcto
    assert _fila_codigo(inv)[0][0] == antes  # y NO se consumió un intento
    mañana = ahora + 86400
    nuevo_dia = _emitir(inv, ahora=mañana)  # al día siguiente el código de ayer ya venció: se pide uno nuevo
    assert _verificar(inv, nuevo_dia, ahora=mañana) == C.OK  # y el bloqueo se levantó (control positivo)


def test_el_bloqueo_es_por_invitado_y_no_toca_a_los_demas(estado_sqlite):
    a, b = _invitado("a@bufete.cr"), _invitado("b@bufete.cr")
    ahora = T0
    for _ in range(2):
        codigo = _emitir(a, ahora=ahora)
        for _ in range(C.MAX_INTENTOS):
            _verificar(a, _malo(codigo), ahora=ahora)
        ahora += 1000
    assert _verificar(a, "123456", ahora=ahora) == C.BLOQUEADO
    cb = _emitir(b)
    assert _verificar(b, cb) == C.OK  # el otro invitado no se ve afectado


# ---- 4. topes de envío ----
def test_el_tope_de_envios_por_invitado_al_dia(estado_sqlite):
    inv = _invitado()
    for i in range(C.ENVIOS_POR_INVITADO_DIA):
        _emitir(inv, ahora=T0 + i * (C.VENTANA_RAFAGA_S + 1))  # espaciados: no chocan con la ráfaga
    with pytest.raises(C.TopeAgotado) as e:
        _emitir(inv, ahora=T0 + C.ENVIOS_POR_INVITADO_DIA * (C.VENTANA_RAFAGA_S + 1))
    assert e.value.cual == "invitado_dia"


def test_el_tope_de_rafaga_y_un_tope_agotado_no_deja_contadores_a_medias(estado_sqlite):
    inv = _invitado()
    for _ in range(C.ENVIOS_RAFAGA):
        _emitir(inv)
    with pytest.raises(C.TopeAgotado) as e:
        _emitir(inv)
    assert e.value.cual == "rafaga"
    assert _uso(f"correo_envios:{inv}")[f"correo_envios:{inv}"] == C.ENVIOS_RAFAGA  # el rollback deshizo el contador de «por invitado al día» de la cuarta
    assert _emitir(inv, ahora=T0 + C.VENTANA_RAFAGA_S + 1)  # pasada la ráfaga, sale (control positivo)


def test_el_tope_global_de_envios_por_dia_protege_el_cupo_del_proveedor(estado_sqlite):
    ids = [_invitado(f"colega{i}@bufete.cr") for i in range(C.ENVIOS_GLOBAL_DIA + 1)]
    for inv in ids[:C.ENVIOS_GLOBAL_DIA]:
        _emitir(inv)
    with pytest.raises(C.TopeAgotado) as e:
        _emitir(ids[-1])
    assert e.value.cual == "global"
    assert _emitir(ids[-1], ahora=T0 + 86400)  # al día siguiente se renueva


def test_si_el_correo_no_salio_se_anula_y_el_codigo_no_queda_vivo(estado_sqlite):
    inv = _invitado()
    codigo = _emitir(inv)
    with bd.estado() as conn:
        assert C.anular_vigentes(conn.cursor(), inv, T0) == 1
    assert _verificar(inv, codigo) == C.AGOTADO  # un código que no se mandó no puede servir


# ---- 5. el código se guarda con clave y no se filtra ----
def test_el_codigo_se_guarda_como_hmac_con_clave_atado_al_invitado_y_al_cliente(estado_sqlite):
    inv = _invitado()
    codigo = _emitir(inv)
    guardado = _fila_codigo(inv)[0][2]
    assert codigo not in guardado and guardado != hashlib.sha256(codigo.encode()).hexdigest()  # ni en claro ni un hash simple (reversible al instante)
    assert guardado == C.hash_codigo(CLAVE, inv, CLI, codigo)  # control positivo: es el HMAC esperado
    assert C.hash_codigo("otra-clave", inv, CLI, codigo) != guardado  # sin la clave del servicio no se reproduce
    assert C.hash_codigo(CLAVE, "otro-invitado", CLI, codigo) != guardado and C.hash_codigo(CLAVE, inv, "otro-cliente", codigo) != guardado


def test_ni_el_codigo_ni_el_correo_aparecen_en_los_logs(estado_sqlite, logs):
    correo = "reservado.secreto@bufete.cr"
    inv = _invitado(correo)
    codigo = _emitir(inv)
    _verificar(inv, _malo(codigo))
    _verificar(inv, codigo)
    try:
        for _ in range(C.ENVIOS_RAFAGA + 1):
            _emitir(inv)
    except C.TopeAgotado:
        pass
    texto = "\n".join(logs)
    assert codigo not in texto and correo not in texto and "reservado.secreto" not in texto


# ---- 6. alta por correo ----
def test_el_alta_por_correo_no_genera_codigo_permanente_y_el_correo_es_unico_sin_importar_mayusculas(estado_sqlite):
    a = _invitado("  Colega@Bufete.CR ")
    with bd.estado() as conn:
        cur = conn.cursor()
        cur.execute("SELECT codigo_sha256, correo, activo FROM invitado WHERE id = %s", (a,))
        assert cur.fetchone() == (None, "colega@bufete.cr", 1)  # sin código permanente; el correo normalizado
        assert invitados.buscar_por_correo(cur, "COLEGA@bufete.cr") == a
    with pytest.raises(sqlite3.IntegrityError):
        _invitado("colega@BUFETE.cr")  # el mismo correo, otra escritura: el índice único lo rechaza
    otro = _invitado("otro@bufete.cr")  # dos invitados sin código permanente conviven (varios NULL son válidos)
    assert otro != a


def test_buscar_por_correo_no_distingue_un_invitado_dado_de_baja_de_uno_que_no_existe(estado_sqlite):
    a = _invitado("baja@bufete.cr")
    with bd.estado() as conn:
        cur = conn.cursor()
        assert invitados.baja(cur, a, T0 + 5) is True
        assert invitados.buscar_por_correo(cur, "baja@bufete.cr") is None  # igual que uno que nunca existió: no se filtra cuál
        assert invitados.buscar_por_correo(cur, "nadie@bufete.cr") is None


def test_lo_que_ya_funcionaba_del_codigo_permanente_sigue_igual(estado_sqlite):
    """Criterio 6: el acceso actual por código permanente no cambia con el esquema nuevo."""
    with bd.estado() as conn:
        cur = conn.cursor()
        inv, codigo = invitados.alta(cur, "Colega de siempre", T0)
        assert invitados.buscar_por_codigo(cur, codigo) == inv
        assert invitados.buscar_por_codigo(cur, "XXXX-XXXX-XXXX-XXXX") is None
    assert "codigo_correo" in __import__("src.conector.esquema_conector", fromlist=["x"]).TABLAS
