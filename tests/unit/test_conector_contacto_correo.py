"""Correo del invitado, autorización de promociones (`contacto.py`) y envío (`correo.py`), listos antes de tener dominio.

Controles: la autorización nace en «no»; `promociones` nunca lista a quien no aceptó ni a quien está de baja; sin configuración
el correo no sale y se dice por qué; la petición sale con `User-Agent: agent` y el destinatario no queda en los logs.
"""

import json
import logging

import pytest

from src.agentika_contacto import contacto as C, correo
from src.conector import bd, invitados


def _alta(cur, etiqueta="Colega"):
    return invitados.alta(cur, etiqueta, 1_000)[0]


def test_la_autorizacion_se_guarda_con_fecha_y_version_y_promociones_lista_solo_a_quien_acepto(estado_sqlite):
    with bd.estado() as conn:
        cur = conn.cursor()
        si, no, baja = _alta(cur, "Acepta"), _alta(cur, "No acepta"), _alta(cur, "De baja")
        assert C.guardar(cur, si, " Colega@Ejemplo.COM ", True, 2_000)
        assert C.guardar(cur, no, "otro@ejemplo.com", False, 2_000)
        assert C.guardar(cur, baja, "baja@ejemplo.com", True, 2_000)
        invitados.baja(cur, baja, 3_000)
        assert C.promociones(cur) == [(si, "Acepta", "colega@ejemplo.com")]
        cur.execute("SELECT promociones_ts, promociones_version FROM invitado WHERE id = %s", (si,))
        assert tuple(cur.fetchone()) == (2_000, C.VERSION_PROMOCIONES)


def test_la_baja_por_enlace_saca_a_la_persona_de_la_lista(estado_sqlite):
    with bd.estado() as conn:
        cur = conn.cursor()
        i = _alta(cur)
        C.guardar(cur, i, "colega@ejemplo.com", True, 2_000)
        assert C.dar_de_baja(cur, "COLEGA@ejemplo.com", 4_000)
        assert C.promociones(cur) == []
        assert not C.dar_de_baja(cur, "nadie@ejemplo.com", 4_000)  # control: un correo que no está no da «ok»


def test_un_correo_sin_forma_no_se_guarda():
    with pytest.raises(ValueError):
        C.normalizar_correo("no-es-un-correo")


def test_un_correo_no_puede_quedar_en_dos_invitados(estado_sqlite):
    with bd.estado() as conn:
        cur = conn.cursor()
        a, b = _alta(cur, "A"), _alta(cur, "B")
        C.guardar(cur, a, "colega@ejemplo.com", True, 2_000)
        with pytest.raises(ValueError):
            C.guardar(cur, b, "COLEGA@ejemplo.com", True, 2_000)
        assert C.guardar(cur, a, "colega@ejemplo.com", False, 3_000)  # control: el mismo invitado sí puede actualizarlo


def test_sin_configuracion_el_correo_no_sale_y_lo_dice(monkeypatch):
    monkeypatch.delenv("CORREO_API_KEY", raising=False)
    monkeypatch.delenv("CORREO_REMITENTE", raising=False)
    r = correo.enviar("colega@ejemplo.com", "Prueba", "Hola", abrir=lambda *a, **k: pytest.fail("no debió llamar al servicio"))
    assert not r.enviado and "no está configurado" in r.motivo


class _Respuesta:
    status = 200

    def __init__(self, cuerpo):
        self._c = cuerpo

    def read(self):
        return self._c

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_configurado_envia_con_user_agent_agent_y_sin_el_destinatario_en_logs(monkeypatch, caplog):
    monkeypatch.setenv("CORREO_API_KEY", "clave-de-prueba")
    monkeypatch.setenv("CORREO_REMITENTE", "Agéntika <no-responder@correo.ejemplo>")
    vistos = []

    def abrir(pedido, timeout):
        vistos.append(pedido)
        return _Respuesta(b'{"id": "abc"}')

    with caplog.at_level(logging.INFO):
        r = correo.enviar("colega@ejemplo.com", "Prueba", "Hola", abrir=abrir)
    assert r.enviado
    assert vistos[0].get_header("User-agent") == "agent"
    assert json.loads(vistos[0].data)["to"] == ["colega@ejemplo.com"]
    assert "colega@ejemplo.com" not in caplog.text


def test_si_el_servicio_no_confirma_no_se_da_por_enviado(monkeypatch):
    monkeypatch.setenv("CORREO_API_KEY", "clave-de-prueba")
    monkeypatch.setenv("CORREO_REMITENTE", "no-responder@correo.ejemplo")
    r = correo.enviar("colega@ejemplo.com", "Prueba", "Hola", abrir=lambda *a, **k: _Respuesta(b"{}"))
    assert not r.enviado and "no confirmó" in r.motivo
