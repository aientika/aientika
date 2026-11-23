"""Cupo de administrador: los topes por invitado se multiplican para los ids de `CONECTOR_ADMINISTRADORES`;
el tope global del servicio no cambia y un invitado común sigue con los topes de siempre."""

from datetime import datetime, timezone

from src.conector import limites as L

AHORA = datetime(2026, 11, 12, 18, 0, tzinfo=timezone.utc)  # 12:00 en Costa Rica


def _topes(herramienta, invitado):
    return {(r.clave.split(":")[-1] if r.clave != "global" else "global", r.ventana.split(":")[0]): r.tope
            for r in L.reglas(herramienta, invitado, AHORA)}


def test_el_administrador_tiene_diez_veces_el_cupo_y_el_global_no_cambia(monkeypatch):
    monkeypatch.setenv(L.VARIABLE_ADMINISTRADORES, "inv-otro, inv-admin")
    f = L.FACTOR_ADMINISTRADOR
    b = _topes("buscar", "inv-admin")
    assert b[("buscar", f"v{L.HORAS_VENTANA}h")] == L.BUSCAR_POR_VENTANA * f
    assert b[("buscar", "sem")] == L.BUSCAR_POR_SEMANA * f
    assert b[("global", "dia")] == L.TOPE_GLOBAL_DIA  # el global protege al servicio: no se multiplica
    assert _topes("ficha", "inv-admin")[("ficha", "dia")] == L.FICHA_POR_DIA * f
    assert _topes("verificar_cita", "inv-admin")[("verificar_cita", "dia")] == L.VERIFICAR_POR_DIA * f
    msg = L.reglas("buscar", "inv-admin", AHORA)[0].nombre
    assert str(L.BUSCAR_POR_VENTANA * f) in msg  # el mensaje dice el cupo real, no el común


def test_un_invitado_comun_sigue_con_los_topes_de_siempre(monkeypatch):
    monkeypatch.setenv(L.VARIABLE_ADMINISTRADORES, "inv-admin")
    b = _topes("buscar", "inv-comun")
    assert b[("buscar", f"v{L.HORAS_VENTANA}h")] == L.BUSCAR_POR_VENTANA and b[("buscar", "sem")] == L.BUSCAR_POR_SEMANA


def test_sin_la_variable_nadie_es_administrador(monkeypatch):
    monkeypatch.delenv(L.VARIABLE_ADMINISTRADORES, raising=False)
    assert not L.es_administrador("inv-admin") and not L.es_administrador(None) and not L.es_administrador("")
    assert _topes("buscar", "inv-admin")[("buscar", "sem")] == L.BUSCAR_POR_SEMANA
