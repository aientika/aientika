"""Capa gratuita dinámica: el presupuesto manda.

Las constantes se importan. Controles: sin presupuesto rigen los fijos; con presupuesto el tope global y el cupo semanal
cambian según lo gastado y las personas activas; si el cálculo falla, rigen los fijos (nunca «sin tope»).
"""

from datetime import datetime

import pytest
from conector_apoyo import cr

from src.conector import bd, limites as L, presupuesto as P

PRESUPUESTO = 175.0
UNIDADES_MES = int((PRESUPUESTO - P.FIJO_MENSUAL_USD) / P.COSTO_UNIDAD_USD)


@pytest.fixture(autouse=True)
def _limpia_cache():
    P._cache.clear()
    yield
    P._cache.clear()


def test_el_tope_del_dia_reparte_lo_que_queda_del_mes_entre_los_dias_que_faltan():
    t = P.calcular(PRESUPUESTO, 0, 10, datetime(2026, 11, 1))
    assert t.global_dia == UNIDADES_MES // 30 and t.dinamico
    # a mitad de mes y con la mitad gastada, el tope diario se mantiene
    assert P.calcular(PRESUPUESTO, UNIDADES_MES // 2, 10, datetime(2026, 11, 16)).global_dia == (UNIDADES_MES - UNIDADES_MES // 2) // 15


def test_si_se_gasto_de_mas_el_tope_baja_y_si_se_gasto_todo_es_cero():
    normal = P.calcular(PRESUPUESTO, 0, 10, datetime(2026, 11, 16)).global_dia
    assert P.calcular(PRESUPUESTO, UNIDADES_MES // 2 + 20000, 10, datetime(2026, 11, 16)).global_dia < normal
    assert P.calcular(PRESUPUESTO, UNIDADES_MES + 5, 10, datetime(2026, 11, 30)).global_dia == 0  # nunca se pasa del mes


def test_el_cupo_semanal_se_reparte_entre_activos_con_piso_y_techo():
    hoy = datetime(2026, 11, 1)
    assert P.calcular(PRESUPUESTO, 0, 1, hoy).buscar_semana == P.TECHO_SEMANAL  # pocos: el techo
    assert P.calcular(PRESUPUESTO, 0, 5000, hoy).buscar_semana == P.PISO_SEMANAL  # muchos: el piso
    medio = P.calcular(PRESUPUESTO, 0, 300, hoy).buscar_semana
    assert P.PISO_SEMANAL < medio < P.TECHO_SEMANAL


def test_presupuesto_que_no_cubre_lo_fijo_o_datos_imposibles_fallan_ruidosamente():
    with pytest.raises(ValueError):
        P.calcular(P.FIJO_MENSUAL_USD, 0, 1, datetime(2026, 11, 1))
    with pytest.raises(ValueError):
        P.calcular(PRESUPUESTO, -1, 1, datetime(2026, 11, 1))


def test_sin_presupuesto_rigen_los_topes_fijos(estado_sqlite, monkeypatch):
    monkeypatch.delenv(P.VARIABLE_PRESUPUESTO, raising=False)
    with bd.estado() as conn:
        assert L.topes_de_hoy(conn.cursor(), cr("2026-11-10 09:00")) == L.FIJOS


def test_con_presupuesto_el_tope_global_sube_y_deja_pasar_lo_que_antes_cortaba(estado_sqlite, monkeypatch):
    monkeypatch.setenv(P.VARIABLE_PRESUPUESTO, str(PRESUPUESTO))
    with bd.estado() as conn:
        conn.cursor().execute("INSERT INTO uso VALUES (%s, %s, %s)", ("global", "dia:2026-11-10", L.TOPE_GLOBAL_DIA))
        hoy = L.topes_de_hoy(conn.cursor(), cr("2026-11-10 09:00"))
    assert hoy.dinamico and hoy.global_dia > L.TOPE_GLOBAL_DIA
    assert L.consumir("buscar", "inv-nuevo", cr("2026-11-10 09:00")).permitido  # con el tope fijo de 1000 se habría cortado


def test_con_presupuesto_el_tope_dinamico_tambien_corta(estado_sqlite, monkeypatch):
    monkeypatch.setenv(P.VARIABLE_PRESUPUESTO, str(PRESUPUESTO))
    with bd.estado() as conn:
        tope = L.topes_de_hoy(conn.cursor(), cr("2026-11-10 09:00")).global_dia
        conn.cursor().execute("INSERT INTO uso VALUES (%s, %s, %s)", ("global", "dia:2026-11-10", tope))
    r = L.consumir("buscar", "inv-nuevo", cr("2026-11-10 09:00"))
    assert not r.permitido and "mañana" in r.mensaje  # control negativo


def test_con_presupuesto_un_solo_activo_recibe_el_techo_semanal(estado_sqlite, monkeypatch):
    monkeypatch.setenv(P.VARIABLE_PRESUPUESTO, str(PRESUPUESTO))
    v = L.consumir("buscar", "inv-a", cr("2026-11-10 09:00"))
    assert v.permitido and f"de {P.TECHO_SEMANAL} esta semana" in v.cupo


def test_si_el_calculo_falla_rigen_los_fijos_y_no_sin_tope(estado_sqlite, monkeypatch):
    monkeypatch.setenv(P.VARIABLE_PRESUPUESTO, "50")  # no cubre lo fijo: el cálculo levanta
    with bd.estado() as conn:
        assert L.topes_de_hoy(conn.cursor(), cr("2026-11-10 09:00")) == L.FIJOS
