"""Código de un solo uso por correo: la lógica y el presupuesto de adivinanza. La pantalla de acceso todavía no lo usa. El código se ata a (invitado, `client_id`) y no a la solicitud OAuth: si Claude Desktop deja de
esperar y el colega reinicia, el código que ya le llegó sigue sirviendo. Se guarda como HMAC con la clave del servicio, nunca
en claro ni como hash sin clave (un código corto con hash simple se revierte al instante). El presupuesto de adivinanza: el intento se descuenta de
forma ATÓMICA antes de comparar, 5 por código; 10 fallos por invitado al día bloquean la verificación hasta el día siguiente; pedir otro código anula los
vigentes; y los envíos tienen tope por invitado, por ráfaga y global, que se toman con el contador atómico de `limites.tomar`.
Un tope agotado levanta `TopeAgotado`: quien llama debe hacer `conn.rollback()` para que no queden contadores a medias. Ni el código ni el correo se
escriben en logs ni en excepciones (el módulo no tiene ningún `print` ni `logging`).
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets

from src.conector import limites

LARGO = 6  # 6 dígitos: lo más sencillo para el usuario (8 sería más robusto; cambiar esta constante basta)
VIGENCIA_S = 600  # 10 minutos
MAX_INTENTOS = 5  # por código
FALLOS_POR_INVITADO_DIA = 10
ENVIOS_POR_INVITADO_DIA = 6
ENVIOS_RAFAGA = 3
VENTANA_RAFAGA_S = 900  # 15 minutos
ENVIOS_GLOBAL_DIA = 60  # por debajo del cupo del proveedor
DESFASE_CR_S = -6 * 3600  # el día de los contadores es el de Costa Rica, como el resto del conector

OK, INCORRECTO, AGOTADO, BLOQUEADO = "ok", "incorrecto", "agotado", "bloqueado"


class TopeAgotado(Exception):
    """Un tope de envíos se agotó. `cual`: «invitado_dia», «rafaga» o «global». Quien llama hace rollback."""

    def __init__(self, cual: str) -> None:
        super().__init__(cual)
        self.cual = cual


def generar(largo: int = LARGO) -> str:
    """Código numérico nuevo, criptográficamente aleatorio."""
    return "".join(secrets.choice("0123456789") for _ in range(largo))


def solo_digitos(texto: str) -> str:
    """Lo que escribió el colega, sin espacios ni guiones."""
    return re.sub(r"\D", "", texto)


def hash_codigo(clave: str | bytes, invitado_id: str, client_id: str, codigo: str) -> str:
    """HMAC-SHA256 del código atado al invitado y al cliente. Sin la clave del servicio no se puede revertir por fuerza bruta."""
    k = clave.encode("utf-8") if isinstance(clave, str) else clave
    return hmac.new(k, f"{invitado_id}|{client_id}|{codigo}".encode("utf-8"), hashlib.sha256).hexdigest()


def _dia(ahora: int) -> str:
    return f"d{(ahora + DESFASE_CR_S) // 86400}"


def anular_vigentes(cur, invitado_id: str, ahora: int) -> int:
    """Marca como usados todos los códigos vigentes del invitado (pedir otro código anula los anteriores). Devuelve cuántos."""
    cur.execute("UPDATE codigo_correo SET usado_ts = %s WHERE invitado_id = %s AND usado_ts IS NULL", (ahora, invitado_id))
    return cur.rowcount


def emitir(cur, invitado_id: str, client_id: str, ahora: int, clave: str | bytes) -> str:
    """Toma los topes de envío, anula los códigos vigentes del invitado y guarda uno nuevo. Devuelve el código en claro, UNA sola vez, para mandarlo.

    Si el envío por correo falla, quien llama debe `anular_vigentes` (un código que no salió no puede quedar vivo). Levanta `TopeAgotado` con un tope agotado.
    """
    dia = _dia(ahora)
    for clave_uso, ventana, tope, cual in (
            (f"correo_envios:{invitado_id}", dia, ENVIOS_POR_INVITADO_DIA, "invitado_dia"),
            (f"correo_rafaga:{invitado_id}", f"r{ahora // VENTANA_RAFAGA_S}", ENVIOS_RAFAGA, "rafaga"),
            ("correo_envios_global", dia, ENVIOS_GLOBAL_DIA, "global")):
        if limites.tomar(cur, clave_uso, ventana, tope) is None:
            raise TopeAgotado(cual)
    anular_vigentes(cur, invitado_id, ahora)
    codigo = generar()
    cur.execute("INSERT INTO codigo_correo (id, invitado_id, client_id, codigo_hmac, vence_ts, intentos, usado_ts, creado_ts) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (secrets.token_hex(8), invitado_id, client_id, hash_codigo(clave, invitado_id, client_id, codigo),
                 ahora + VIGENCIA_S, 0, None, ahora))
    return codigo


def fallos_de_hoy(cur, invitado_id: str, ahora: int) -> int:
    """Cuántos códigos incorrectos lleva el invitado hoy."""
    cur.execute("SELECT unidades FROM uso WHERE clave = %s AND ventana = %s", (f"correo_fallos:{invitado_id}", _dia(ahora)))
    fila = cur.fetchone()
    return int(fila[0]) if fila else 0


def verificar(cur, invitado_id: str, client_id: str, codigo: str, ahora: int, clave: str | bytes) -> str:
    """Compara el código escrito con el vigente del (invitado, cliente). Devuelve `OK`, `INCORRECTO`, `AGOTADO` o `BLOQUEADO`.

    `AGOTADO`: no hay código vigente (venció, ya se usó, lo anuló otro pedido, otro cliente o se acabaron los 5 intentos). `BLOQUEADO`: 10 fallos hoy; en ese
    caso NO se consume un intento. El intento se descuenta con un UPDATE condicional ANTES de comparar, así dos POST en paralelo no pueden probar más de 5
    códigos, y el uso es otro UPDATE condicional (de dos verificaciones correctas simultáneas, solo una gana).
    """
    if fallos_de_hoy(cur, invitado_id, ahora) >= FALLOS_POR_INVITADO_DIA:
        return BLOQUEADO
    # DOS capas de «un solo uso», redundantes A PROPÓSITO (defensa en profundidad): esta sentencia ya exige `usado_ts IS NULL`, y la que marca el uso más abajo lo
    # exige otra vez. Quitar UNA sola no cambia el resultado (la otra la cubre); quitar las DOS permite usar un código dos veces: un test lo atrapa.
    cur.execute("UPDATE codigo_correo SET intentos = intentos + 1 WHERE invitado_id = %s AND client_id = %s AND usado_ts IS NULL "
                "AND vence_ts >= %s AND intentos < %s RETURNING id, codigo_hmac", (invitado_id, client_id, ahora, MAX_INTENTOS))
    fila = cur.fetchone()
    if fila is None:
        return AGOTADO
    esperado = hash_codigo(clave, invitado_id, client_id, solo_digitos(codigo))
    if not hmac.compare_digest(fila[1], esperado):
        limites.tomar(cur, f"correo_fallos:{invitado_id}", _dia(ahora), FALLOS_POR_INVITADO_DIA)  # cuenta el fallo; en el tope no hace nada más
        return INCORRECTO
    cur.execute("UPDATE codigo_correo SET usado_ts = %s WHERE id = %s AND usado_ts IS NULL", (ahora, fila[0]))
    if cur.rowcount != 1:
        return AGOTADO  # otra verificación correcta lo usó un instante antes
    cur.execute("UPDATE invitado SET correo_verificado_ts = %s WHERE id = %s", (ahora, invitado_id))
    return OK
