"""Límites del conector: ventanas fijas de 4 h en hora de Costa Rica, semana lunes-domingo, conteo ANTES de ejecutar, atómico.

Las constantes se IMPORTAN: cambiar 15 por 20 no rompe el test, pero sí lo rompería que el código dejara de aplicarlas.
Controles negativos: una llamada de más es rechazada; una de una ventana nueva pasa. El paralelismo usa hilos reales sobre el mismo
SQL de producción (SQLite serializa las escrituras; el bloqueo de filas de Postgres se verifica en vivo).
"""

import threading
from datetime import timedelta, timezone

from conector_apoyo import cr

from src.conector import bd, limites as L


def gastar(n, inv="inv-a", ahora=None, herramienta="buscar"):
    ahora = ahora or cr("2026-11-10 09:00")
    return [L.consumir(herramienta, inv, ahora) for _ in range(n)]


def test_pasan_exactamente_las_unidades_de_la_ventana_y_la_siguiente_se_rechaza(estado_sqlite):
    v = gastar(L.BUSCAR_POR_VENTANA + 1)
    assert all(x.permitido for x in v[:-1])
    assert not v[-1].permitido  # control negativo


def test_el_mensaje_dice_cuanto_se_agoto_y_la_hora_exacta_de_renovacion(estado_sqlite):
    ultimo = gastar(L.BUSCAR_POR_VENTANA + 1, ahora=cr("2026-11-10 09:00"))[-1]
    assert "12:00" in ultimo.mensaje and "hora de Costa Rica" in ultimo.mensaje and str(L.BUSCAR_POR_VENTANA) in ultimo.mensaje


def test_la_ventana_se_renueva_en_la_frontera_de_las_4_horas(estado_sqlite):
    gastar(L.BUSCAR_POR_VENTANA, ahora=cr("2026-11-10 11:59"))
    assert not L.consumir("buscar", "inv-a", cr("2026-11-10 11:59")).permitido
    assert L.consumir("buscar", "inv-a", cr("2026-11-10 12:00")).permitido  # ventana nueva


def test_las_seis_ventanas_del_dia_son_0_4_8_12_16_20(estado_sqlite):
    inicios = {L.inicio_ventana(cr(f"2026-11-10 {h:02d}:30")).hour for h in range(24)}
    assert inicios == {0, 4, 8, 12, 16, 20}


def test_el_tope_semanal_corta_aunque_la_ventana_este_libre(estado_sqlite):
    lunes, usadas, k = cr("2026-11-09 00:00"), 0, 0
    while usadas < L.BUSCAR_POR_SEMANA:  # una ventana tras otra, todas dentro de la misma semana
        n = min(L.BUSCAR_POR_VENTANA, L.BUSCAR_POR_SEMANA - usadas)
        assert all(x.permitido for x in gastar(n, ahora=lunes + timedelta(hours=L.HORAS_VENTANA * k)))
        usadas, k = usadas + n, k + 1
    r = L.consumir("buscar", "inv-a", cr("2026-11-14 20:00"))  # sábado: ventana nueva y vacía, semana agotada
    assert not r.permitido and "semana" in r.mensaje and "lunes 16" in r.mensaje


def test_la_semana_se_renueva_el_lunes(estado_sqlite):
    assert L.inicio_semana(cr("2026-11-15 23:59")) == cr("2026-11-09 00:00")  # domingo -> lunes anterior
    assert L.inicio_semana(cr("2026-11-16 00:00")) == cr("2026-11-16 00:00")


def test_todo_o_nada_si_falla_la_semana_no_se_descuenta_la_ventana(estado_sqlite):
    with bd.estado() as conn:  # semana ya agotada, ventana vacía
        conn.cursor().execute("INSERT INTO uso VALUES (%s, %s, %s)", ("inv-a:buscar", "sem:2026-11-09", L.BUSCAR_POR_SEMANA))
    assert not L.consumir("buscar", "inv-a", cr("2026-11-10 09:00")).permitido
    with bd.estado() as conn:
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM uso WHERE ventana LIKE 'v%'")
        assert cur.fetchone()[0] == 0  # la ventana no quedó gastada


def test_llamadas_en_paralelo_no_pasan_el_tope(estado_sqlite):
    resultados, barrera = [], threading.Barrier(24)

    def llamar():
        barrera.wait()
        resultados.append(L.consumir("buscar", "inv-a", cr("2026-11-10 09:00")).permitido)

    hilos = [threading.Thread(target=llamar) for _ in range(24)]
    [h.start() for h in hilos]
    [h.join() for h in hilos]
    assert sum(resultados) == L.BUSCAR_POR_VENTANA  # ni una de más, ni una de menos


def test_cada_invitado_tiene_su_cupo(estado_sqlite):
    gastar(L.BUSCAR_POR_VENTANA, inv="inv-a")
    assert not L.consumir("buscar", "inv-a", cr("2026-11-10 09:00")).permitido
    assert L.consumir("buscar", "inv-b", cr("2026-11-10 09:00")).permitido


def test_ficha_y_verificar_tienen_tope_diario_propio_y_no_gastan_el_de_buscar(estado_sqlite):
    assert all(x.permitido for x in gastar(L.FICHA_POR_DIA, herramienta="ficha"))
    assert not L.consumir("ficha", "inv-a", cr("2026-11-10 09:00")).permitido
    assert all(x.permitido for x in gastar(L.VERIFICAR_POR_DIA, herramienta="verificar_cita"))
    assert not L.consumir("verificar_cita", "inv-a", cr("2026-11-10 09:00")).permitido
    assert L.consumir("buscar", "inv-a", cr("2026-11-10 09:00")).permitido  # el cupo de búsqueda está intacto
    assert L.consumir("ayuda", "inv-a", cr("2026-11-10 09:00")).permitido  # `ayuda` nunca gasta


def test_reportar_tiene_su_tope_y_no_toca_el_global(estado_sqlite):
    assert all(x.permitido for x in gastar(L.REPORTAR_POR_DIA, herramienta="reportar"))
    assert not L.consumir("reportar", "inv-a", cr("2026-11-10 09:00")).permitido
    with bd.estado() as conn:
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM uso WHERE clave = 'global'")
        assert cur.fetchone()[0] == 0


def test_el_tope_global_del_dia_corta_a_todos(estado_sqlite):
    with bd.estado() as conn:
        conn.cursor().execute("INSERT INTO uso VALUES (%s, %s, %s)", ("global", "dia:2026-11-10", L.TOPE_GLOBAL_DIA))
    r = L.consumir("buscar", "inv-nuevo", cr("2026-11-10 09:00"))
    assert not r.permitido and "tope diario" in r.mensaje and "mañana" in r.mensaje


def test_devolver_restituye_la_unidad(estado_sqlite):
    gastar(L.BUSCAR_POR_VENTANA)
    assert not L.consumir("buscar", "inv-a", cr("2026-11-10 09:00")).permitido
    L.devolver("buscar", "inv-a", cr("2026-11-10 09:00"))
    assert L.consumir("buscar", "inv-a", cr("2026-11-10 09:00")).permitido


def test_el_cupo_en_palabras_cuenta_lo_que_queda(estado_sqlite):
    r = gastar(3)[-1]
    assert f"{L.BUSCAR_POR_VENTANA - 3} de {L.BUSCAR_POR_VENTANA}" in r.cupo and "12:00" in r.cupo


def test_servicio_24_horas_atiende_de_noche(estado_sqlite):
    """: sin esto, a las 23:00 el conector contestaba «fuera de horario» aunque la base estuviera prendida."""
    assert L.SERVICIO_24_HORAS
    for hora in ("2026-11-10 23:00", "2026-11-11 00:00", "2026-11-11 03:30", "2026-11-11 06:59", "2026-11-11 12:00"):
        assert not L.fuera_de_horario(cr(hora)), hora
    assert L.hora_legible(cr("2026-11-11 00:00"), cr("2026-11-10 21:00")) == "mañana a las 0:00"


def test_horario_7_a_23_hora_de_costa_rica(estado_sqlite, monkeypatch):
    monkeypatch.setattr(L, "SERVICIO_24_HORAS", False)  # el horario de 7 a 23 queda como vuelta atrás
    assert L.fuera_de_horario(cr("2026-11-10 06:30")) and L.fuera_de_horario(cr("2026-11-10 23:00"))
    assert L.fuera_de_horario(cr("2026-11-10 00:00"))
    assert L.fuera_de_horario(cr("2026-11-10 06:59")) and not L.fuera_de_horario(cr("2026-11-10 07:00")) and not L.fuera_de_horario(cr("2026-11-10 22:59"))


def test_la_hora_se_mide_en_costa_rica_aunque_el_reloj_venga_en_utc(estado_sqlite):
    utc = cr("2026-11-10 22:30").astimezone(timezone.utc)  # ya es 04:30 UTC del día 11
    assert not L.fuera_de_horario(utc)
    assert L.inicio_ventana(utc).hour == 20


def test_una_renovacion_a_medianoche_se_dice_desde_que_abre_el_servicio(estado_sqlite, monkeypatch):
    monkeypatch.setattr(L, "SERVICIO_24_HORAS", False)
    assert L.hora_legible(cr("2026-11-11 00:00"), cr("2026-11-10 21:00")) == "mañana a las 7:00"
    assert L.hora_legible(cr("2026-11-16 00:00"), cr("2026-11-14 10:00")) == "el lunes 16 a las 7:00"


def test_resumen_para_ayuda_muestra_lo_que_queda_con_la_hora(estado_sqlite):
    gastar(5)
    r = L.resumen("inv-a", cr("2026-11-10 09:00"))
    assert r["buscar:v4h"]["quedan"] == L.BUSCAR_POR_VENTANA - 5
    assert r["buscar:sem"]["quedan"] == L.BUSCAR_POR_SEMANA - 5
    assert "12:00" in r["buscar:v4h"]["se_renueva"]


def test_todo_texto_del_horario_dice_la_hora_de_apertura_de_la_constante():
    # Un texto que dijera una hora de apertura distinta de la constante prometería una hora
    # en que la base está apagada. Control positivo: hay textos con horario; negativo: ninguno con otra hora de apertura.
    import re
    from pathlib import Path
    carpeta = Path(L.__file__).parent
    archivos = [*carpeta.glob("*.py"), carpeta / "sitio" / "index.html"]
    patron = re.compile(r"(\d{1,2}):00 ?(?:a|-) ?" + str(L.HORA_CIERRE) + ":00")
    horas = [(p.name, m.group(1)) for p in archivos for m in patron.finditer(p.read_text(encoding="utf-8"))]
    assert len(horas) >= 2, horas
    assert all(h == str(L.HORA_APERTURA) for _, h in horas), [x for x in horas if x[1] != str(L.HORA_APERTURA)]
