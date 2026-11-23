"""Invitados (código mostrado una vez, solo su hash en la base, baja que revoca) y presupuesto de Voyage de consultas (tope mensual, atómico)."""

import threading
from datetime import datetime, timezone

import pytest
from conector_apoyo import volcar_tablas

from src.conector import bd, invitados as I, presupuesto_voyage as P
from src.indice.tope_voyage import PRECIO_POR_MILLON


def test_el_codigo_tiene_formato_dictable_y_no_se_repite():
    cod = {I.generar_codigo() for _ in range(200)}
    assert len(cod) == 200
    assert all(len(c) == I.LARGO + 3 and set(c.replace("-", "")) <= set(I.ALFABETO) for c in cod)
    assert not set("ILO01") & set(I.ALFABETO)


def test_se_normaliza_al_comparar_mayusculas_y_guiones_dan_el_mismo_hash():
    assert I.hash_codigo("abcd-efgh-jkmn-pqrs") == I.hash_codigo(" ABCD EFGH JKMN PQRS ")


def test_alta_guarda_solo_el_hash_y_el_codigo_busca_al_invitado(estado_sqlite):
    with bd.estado() as conn:
        id_, codigo = I.alta(conn.cursor(), "Colega Uno", 1000)
    volcado = volcar_tablas(estado_sqlite)
    assert codigo not in volcado and codigo.replace("-", "") not in volcado and I.hash_codigo(codigo) in volcado
    with bd.estado() as conn:
        assert I.buscar_por_codigo(conn.cursor(), codigo.lower()) == id_
        assert I.buscar_por_codigo(conn.cursor(), "AAAA-AAAA-AAAA-AAAA") is None  # control negativo


def test_la_baja_desactiva_y_revoca_todas_las_credenciales(estado_sqlite):
    with bd.estado() as conn:
        cur = conn.cursor()
        id_, codigo = I.alta(cur, "Colega", 1000)
        for jti in ("j1", "j2"):
            cur.execute("INSERT INTO credencial (jti, invitado_id, client_id, creado_ts, expira_ts) VALUES (%s,%s,%s,%s,%s)",
                        (jti, id_, "c", 1000, 99999))
        assert I.baja(cur, id_, 2000) is True
        assert I.buscar_por_codigo(cur, codigo) is None
        cur.execute("SELECT count(*) FROM credencial WHERE revocada_ts IS NOT NULL")
        assert cur.fetchone()[0] == 2
        assert I.baja(cur, "inv-no-existe", 2000) is False


def test_listar_nunca_expone_codigo_ni_hash(estado_sqlite):
    with bd.estado() as conn:
        _, codigo = I.alta(conn.cursor(), "Colega", 1000)
        texto = str(I.listar(conn.cursor()))
    assert codigo not in texto and I.hash_codigo(codigo) not in texto


# --- presupuesto de Voyage ---------------------------------------------------------------------------------------------

def reloj(mes=11):
    return lambda: datetime(2026, mes, 10, 12, tzinfo=timezone.utc)


def test_el_tope_en_tokens_sale_del_precio_y_del_dolar():
    assert P.TOPE_TOKENS_MES == int(P.TOPE_USD_MES / PRECIO_POR_MILLON["voyage-4"] * 1_000_000)
    assert P.TOPE_TOKENS_MES * PRECIO_POR_MILLON["voyage-4"] / 1_000_000 <= P.TOPE_USD_MES


def test_reserva_hasta_el_tope_y_lo_que_pasa_se_rechaza(estado_sqlite):
    r = P.reservar_con_reloj(reloj())
    r(P.TOPE_TOKENS_MES - 10)
    r(10)
    with pytest.raises(P.PresupuestoAgotado):
        r(1)  # control negativo
    assert P.fraccion_usada(reloj()()) == 1.0


def test_mes_nuevo_mes_nuevo_presupuesto(estado_sqlite):
    P.reservar_con_reloj(reloj(11))(P.TOPE_TOKENS_MES)
    P.reservar_con_reloj(reloj(12))(100)  # diciembre arranca de cero


def test_una_reserva_que_no_cabe_no_consume_nada(estado_sqlite):
    r = P.reservar_con_reloj(reloj())
    r(P.TOPE_TOKENS_MES - 5)
    with pytest.raises(P.PresupuestoAgotado):
        r(6)
    r(5)  # los 5 que quedaban siguen disponibles


def test_reservas_en_paralelo_no_pasan_el_tope(estado_sqlite):
    r, ok, barrera = P.reservar_con_reloj(reloj()), [], threading.Barrier(16)
    trozo = P.TOPE_TOKENS_MES // 10

    def llamar():
        barrera.wait()
        try:
            r(trozo)
            ok.append(1)
        except P.PresupuestoAgotado:
            pass

    hilos = [threading.Thread(target=llamar) for _ in range(16)]
    [h.start() for h in hilos]
    [h.join() for h in hilos]
    assert len(ok) == 10


def test_sin_reservar_voyage_no_se_llama(monkeypatch):
    from src.conector.voyage_consulta import PresupuestoNoInyectado, embeber_consulta
    monkeypatch.setenv("VOYAGE_OPT_OUT_CONFIRMADO", "prueba")
    with pytest.raises(PresupuestoNoInyectado):
        embeber_consulta("una consulta cualquiera")


# --- script de invitados -----------------------------------------------------------------------------------------------

def script():
    import importlib.util
    from pathlib import Path
    ruta = Path(__file__).resolve().parents[2] / "scripts" / "conector_invitados.py"
    spec = importlib.util.spec_from_file_location("conector_invitados", ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def test_el_script_muestra_el_codigo_una_vez_y_listar_nunca(estado_sqlite, capsys):
    s = script()
    assert s.main(["alta", "--etiqueta", "Colega Dos"]) == 0
    salida = capsys.readouterr().out
    codigo = salida.split("no se guarda): ")[1].strip()
    assert I.generar_codigo().count("-") == codigo.count("-") == 3
    assert s.main(["listar"]) == 0
    listado = capsys.readouterr().out
    assert "Colega Dos" in listado and "activo" in listado and codigo not in listado and I.hash_codigo(codigo) not in listado
    id_ = listado.split()[0]
    assert s.main(["baja", id_]) == 0 and "de baja" in (s.main(["listar"]), capsys.readouterr().out)[1]
    assert s.main(["baja", "inv-fantasma"]) == 1  # control negativo


def test_el_script_no_imprime_tokens_ni_hashes(estado_sqlite, capsys):
    s = script()
    s.main(["alta", "--etiqueta", "Colega Tres"])
    s.main(["listar"])
    s.main(["esquema"])
    salida = capsys.readouterr().out
    assert "eyJ" not in salida and len([p for p in salida.split() if len(p) == 64 and all(c in "0123456789abcdef" for c in p)]) == 0


def test_el_alta_registra_fecha_y_origen_manual_o_automatico(estado_sqlite):
    #
    with bd.estado() as conn:
        cur = conn.cursor()
        I.alta(cur, "A mano", 1000)
        I.alta(cur, "Por formulario", 2000, origen="automatico")
        filas = {f[1]: (f[4], f[5]) for f in I.listar(cur)}
        assert filas == {"A mano": (1000, "manual"), "Por formulario": (2000, "automatico")}
        with pytest.raises(ValueError):
            I.alta(cur, "Otro", 3000, origen="robot")  # control: un origen desconocido no entra


def test_la_migracion_marca_como_manuales_a_los_invitados_viejos():
    from src.conector.esquema_conector import MIGRACIONES
    assert "ALTER TABLE invitado ADD COLUMN IF NOT EXISTS origen TEXT" in MIGRACIONES
    assert "UPDATE invitado SET origen = 'manual' WHERE origen IS NULL" in MIGRACIONES
