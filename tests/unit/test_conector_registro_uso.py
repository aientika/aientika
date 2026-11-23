"""Registro de uso con el texto de las consultas.

Cada detector con su control: una credencial con el aviso v1 o sin aviso (anterior a la versión) NO deja texto, y una con el
aviso v2 sí; la purga a 90 días borra lo viejo y conserva lo reciente; el texto queda en la tabla y en ningún log, ni siquiera
cuando el registro falla con una excepción que lo repite. El flujo OAuth se prueba de punta a punta: la versión que muestra la pantalla
llega a la credencial y de ahí a la herramienta. Las constantes se importan, no se escriben a mano.
"""

import asyncio
import contextlib
import importlib.util
import json
from pathlib import Path

import pytest
from conector_apoyo import cr, invitar
from test_conector_oauth import flujo_completo
from test_conector_servidor import texto_de_herramienta

from src.conector import bd, esquema_conector, herramientas as H, invitados, limites as L, oauth, pantalla, registro
from src.conector.registro import AVISO_MINIMO_TEXTO, DIAS_RETENCION_CONSULTAS

FRASE_MARCADA = "ZXQ-consulta-registrada-confidencial-4471"
RESPUESTA = {"cobertura": "COBERTURA: prueba.", "semantica_usada": True, "total": 1, "resultados": [{"id": "sen-1-0001-0000001"}],
             "solo_literal": [], "aviso": None, "literal": {}}
AHORA = cr("2026-11-12 09:00")
RAIZ = Path(__file__).resolve().parents[2]


class ConexionFalsa:
    def close(self):
        pass


@pytest.fixture
def h(estado_sqlite, monkeypatch):
    """Herramientas a las 09:00 CR con la base y el núcleo sustituidos (como en test_conector_herramientas)."""
    monkeypatch.setattr(bd, "conectar_lectura", lambda: ConexionFalsa())
    monkeypatch.setattr(H, "buscar_nucleo", lambda conn, consulta, *a: dict(RESPUESTA))
    monkeypatch.setattr(H, "ficha_nucleo", lambda conn, id: {"id": id, "por_tanto": "Se declara sin lugar."})
    monkeypatch.setattr(H, "verificar_nucleo", lambda conn, id, frase: {"id": id, "literal": True})
    return H.Herramientas(embeber=lambda q: [0.0] * 1024, reloj=lambda: AHORA)


def correr(coro):
    return asyncio.run(coro)


def _estado_que_falla_en(tabla, original):
    """`bd.estado` cuyo cursor levanta, con los PARÁMETROS en el mensaje, toda sentencia sobre `tabla`; el resto pasa."""
    class Cursor:
        def __init__(self, cur):
            self._cur = cur

        def execute(self, sql, params=()):
            if tabla in sql:
                raise RuntimeError(f"falló con {params}")
            return self._cur.execute(sql, params)

        def __getattr__(self, nombre):
            return getattr(self._cur, nombre)

    @contextlib.contextmanager
    def estado():
        with original() as conn:
            yield type("Conn", (), {"cursor": lambda _s: Cursor(conn.cursor()), "__getattr__": lambda _s, n: getattr(conn, n)})()
    return estado


def filas_consulta(order="ts"):
    with bd.estado() as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT ts, invitado_id, herramienta, texto, filtros FROM conector_consulta ORDER BY {order}")
        return [tuple(f) for f in cur.fetchall()]


def las_tres(herr, aviso):
    correr(herr.buscar("inv-a", "cli", f"responsabilidad {FRASE_MARCADA}", "Sala Primera", 2025, aviso_version=aviso))
    correr(herr.ficha("inv-a", "cli", "sen-1-0001-0000001", aviso_version=aviso))
    correr(herr.verificar_cita("inv-a", "cli", "sen-1-0001-0000002", f"{FRASE_MARCADA} es una frase larga", aviso_version=aviso))


# --- control negativo y positivo ------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("aviso", [None, AVISO_MINIMO_TEXTO - 1])
def test_con_aviso_v1_o_sin_aviso_no_se_guarda_el_texto(h, aviso):
    las_tres(h, aviso)
    assert filas_consulta() == []
    with bd.estado() as conn:  # control: la llamada sí quedó registrada, así que el cero no es un registro apagado
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM conector_llamada")
        assert cur.fetchone()[0] == 3


def test_con_aviso_v2_se_guarda_el_texto_los_filtros_y_el_id(h):
    las_tres(h, AVISO_MINIMO_TEXTO)
    filas = filas_consulta("herramienta")
    ts = int(AHORA.timestamp())
    assert filas == [
        (ts, "inv-a", "buscar", f"responsabilidad {FRASE_MARCADA}", json.dumps({"despacho": "Sala Primera", "anno": 2025})),
        (ts, "inv-a", "ficha", "sen-1-0001-0000001", None),
        (ts, "inv-a", "verificar_cita", f"{FRASE_MARCADA} es una frase larga", json.dumps({"id": "sen-1-0001-0000002"})),
    ]


def test_el_aviso_de_la_pantalla_es_de_los_que_guardan_texto_y_lo_dice():
    assert pantalla.AVISO_VERSION >= AVISO_MINIMO_TEXTO
    assert "durante 90 días, el texto de tus búsquedas" in pantalla.AVISO_PRIVACIDAD
    assert f"{DIAS_RETENCION_CONSULTAS} días" in pantalla.AVISO_PRIVACIDAD
    assert "Qué NO se guarda" not in pantalla.AVISO_PRIVACIDAD  # la promesa vieja ya no se le hace a quien autoriza hoy


def test_ayuda_y_reportar_no_guardan_texto(h):
    correr(h.ayuda("inv-a", "cli"))
    correr(h.reportar("inv-a", "cli", "resumen", "problema"))
    assert filas_consulta() == []


def test_tambien_se_guarda_si_la_llamada_falla_o_topa(h, monkeypatch):
    monkeypatch.setattr(H, "ficha_nucleo", lambda conn, id: (_ for _ in ()).throw(bd.BDNoDisponible("x")))
    correr(h.ficha("inv-a", "cli", "sen-caida", aviso_version=AVISO_MINIMO_TEXTO))
    monkeypatch.setattr(L, "consumir", lambda *a, **k: L.Veredicto(False, mensaje="sin cupo"))
    correr(h.buscar("inv-a", "cli", "consulta topada", aviso_version=AVISO_MINIMO_TEXTO))
    assert [f[3] for f in filas_consulta()] == ["sen-caida", "consulta topada"]


# --- purga a 90 días ------------------------------------------------------------------------------------------------------------

def test_cada_insercion_borra_lo_anterior_a_90_dias_y_conserva_lo_reciente(estado_sqlite):
    ts = int(AHORA.timestamp())
    dia = 86400
    registro.registrar_consulta(ts - (DIAS_RETENCION_CONSULTAS + 1) * dia, "inv-a", "buscar", "vieja")
    registro.registrar_consulta(ts - (DIAS_RETENCION_CONSULTAS - 1) * dia, "inv-a", "buscar", "reciente")
    assert [f[3] for f in filas_consulta()] == ["vieja", "reciente"]  # control: la vieja estaba antes de la purga
    registro.registrar_consulta(ts, "inv-a", "buscar", "nueva")
    assert [f[3] for f in filas_consulta()] == ["reciente", "nueva"]


# ---: el texto no va a los logs -------------------------------------------------------------------------------------------

def test_qa11_el_texto_se_guarda_en_la_tabla_pero_no_en_los_logs(h, logs, monkeypatch):
    monkeypatch.setattr(H, "buscar_nucleo", lambda conn, consulta, *a: (_ for _ in ()).throw(RuntimeError(f"tsquery: {consulta}")))
    correr(h.buscar("inv-a", "cli", f"derecho {FRASE_MARCADA}", aviso_version=AVISO_MINIMO_TEXTO))
    assert [f[3] for f in filas_consulta()] == [f"derecho {FRASE_MARCADA}"]  # control positivo: el texto sí se guardó
    assert any("falló buscar" in x for x in logs)  # control positivo: el fallo sí se logueó (solo el tipo)
    assert not [x for x in logs if FRASE_MARCADA in x]


def test_qa11_si_falla_el_registro_de_la_consulta_el_aviso_no_trae_el_texto_y_la_respuesta_sale(h, logs, monkeypatch):
    """Como un error de pg8000, la excepción repite el parámetro del INSERT, es decir, la consulta."""
    monkeypatch.setattr(registro.bd, "estado", _estado_que_falla_en("conector_consulta", registro.bd.estado))
    monkeypatch.setattr(L, "consumir", lambda *a, **k: L.Veredicto(True))
    r = correr(h.buscar("inv-a", "cli", f"derecho {FRASE_MARCADA}", aviso_version=AVISO_MINIMO_TEXTO))
    assert r["total"] == 1  # el registro nunca voltea la llamada
    avisos = [x for x in logs if "no se pudo anotar la consulta" in x]
    assert avisos and "RuntimeError" in avisos[0]
    assert not [x for x in logs if FRASE_MARCADA in x]
    monkeypatch.undo()
    with bd.estado() as conn:  # la fila de la llamada sí quedó: falló solo la del texto
        cur = conn.cursor()
        cur.execute("SELECT herramienta, resultado FROM conector_llamada")
        assert [tuple(f) for f in cur.fetchall()] == [("buscar", "ok")]


# --- de punta a punta: pantalla -> código -> credencial -> herramienta ----------------------------------------------------------

def test_flujo_oauth_lleva_el_aviso_de_la_pantalla_hasta_la_herramienta(servidor_http):
    c, _ = servidor_http
    token, *_ = flujo_completo(c)
    with bd.estado() as conn:
        cur = conn.cursor()
        cur.execute("SELECT aviso_version FROM oauth_codigo")
        assert [f[0] for f in cur.fetchall()] == [pantalla.AVISO_VERSION]
        cur.execute("SELECT aviso_version FROM credencial")
        assert [f[0] for f in cur.fetchall()] == [pantalla.AVISO_VERSION]
    texto_de_herramienta(c, token, "buscar", {"consulta": f"daño moral {FRASE_MARCADA}", "anno": 2024})
    texto_de_herramienta(c, token, "ayuda", {})
    filas = filas_consulta()
    assert [(f[2], f[3], f[4]) for f in filas] == [("buscar", f"daño moral {FRASE_MARCADA}", json.dumps({"anno": 2024}))]


def test_una_credencial_vieja_sin_aviso_no_deja_texto_por_http(servidor_http):
    c, _ = servidor_http
    token, *_ = flujo_completo(c)
    with bd.estado() as conn:
        conn.cursor().execute("UPDATE credencial SET aviso_version = NULL")  # como las emitidas antes de esta versión
    r = texto_de_herramienta(c, token, "buscar", {"consulta": f"daño moral {FRASE_MARCADA}"})
    assert "error" in r or "resultados" in r  # la herramienta contestó (con la base caída del fixture, en palabras)
    assert filas_consulta() == []
    with bd.estado() as conn:  # control: la llamada sí llegó al registro
        cur = conn.cursor()
        cur.execute("SELECT herramienta FROM conector_llamada")
        assert [f[0] for f in cur.fetchall()] == ["buscar"]


def test_load_access_token_lee_el_aviso_en_la_misma_consulta(estado_sqlite, monkeypatch):
    monkeypatch.setenv("CONECTOR_FIRMA_SECRET", "s" * 48)
    monkeypatch.setattr(L, "fuera_de_horario", lambda ahora: False)
    from src.conector.token import emitir_jwt
    inv, _ = invitar()
    token, vence = emitir_jwt(inv, "jti-prueba")
    with bd.estado() as conn:
        conn.cursor().execute("INSERT INTO credencial (jti, invitado_id, client_id, creado_ts, expira_ts, aviso_version) "
                              "VALUES (%s, %s, %s, %s, %s, %s)", ("jti-prueba", inv, "cli-1", 1, vence, 2))
    consultas = []
    fabrica = bd._fabricas["estado"]

    def contando():
        consultas.append(1)
        return fabrica()
    bd.usar(estado=contando)
    t = asyncio.run(oauth.ProveedorConector("https://conector.test").load_access_token(token))
    assert t.client_id == "cli-1" and t.aviso_version == 2 and t.verificado and consultas == [1]


# --- migración ------------------------------------------------------------------------------------------------------------------

def _ddl_viejo():
    """El esquema anterior al registro de uso: sin `aviso_version`, sin `invitado.origen` y sin `conector_consulta`."""
    return [s.replace(", correo TEXT, acepta_promociones BOOLEAN, promociones_ts BIGINT, promociones_version INT, correo_verificado_ts BIGINT", "")
             .replace("codigo_sha256 TEXT UNIQUE", "codigo_sha256 TEXT NOT NULL UNIQUE")  # v2: antes el código permanente era obligatorio
             .replace(", aviso_version INT", "").replace(", origen TEXT", "") for s in esquema_conector.DDL
            if "conector_consulta" not in s and "codigo_correo" not in s]


def test_la_migracion_pone_al_dia_una_base_con_el_esquema_viejo(tmp_path):
    ruta = str(tmp_path / "vieja.db")
    conn = bd.fabrica_sqlite(ruta)()
    cur = conn.cursor()
    for s in _ddl_viejo():
        cur.execute(s)
    cur.execute("INSERT INTO invitado (id, codigo_sha256, etiqueta, activo, creado_ts) VALUES ('inv-viejo', 'h', 'Viejo', 1, 1)")
    conn.commit()
    cur.execute("PRAGMA table_info(credencial)")
    assert "aviso_version" not in {f[1] for f in cur.fetchall()}  # control: de verdad es el esquema viejo
    esquema_conector.crear_esquema(conn)  # la parte común (tablas nuevas)
    for s in esquema_conector.MIGRACIONES:  # SQLite no entiende IF NOT EXISTS en ADD COLUMN; Postgres sí (y es lo que corre)
        if " ALTER COLUMN " in s:  # v2: solo Postgres. SQLite no puede quitar un NOT NULL; en SQLite una base nueva ya nace con la columna nulable
            continue
        conn.cursor().execute(s.replace(" IF NOT EXISTS", ""))
    conn.commit()
    for tabla in ("credencial", "oauth_codigo"):
        c2 = conn.cursor()
        c2.execute(f"PRAGMA table_info({tabla})")
        assert "aviso_version" in {f[1] for f in c2.fetchall()}
    c2 = conn.cursor()
    c2.execute("PRAGMA table_info(conector_consulta)")
    assert {f[1] for f in c2.fetchall()} == {"ts", "invitado_id", "herramienta", "texto", "filtros"}
    c2.execute("SELECT origen FROM invitado WHERE id = 'inv-viejo'")
    assert c2.fetchone()[0] == "manual"  # los invitados de antes de la columna quedan como creados a mano
    # La tabla de códigos de correo y la columna de verificación llegan con la migración; el invitado de antes sigue ahí con su código
    c2.execute("PRAGMA table_info(invitado)")
    assert "correo_verificado_ts" in {f[1] for f in c2.fetchall()}
    c2.execute("SELECT codigo_hmac FROM codigo_correo WHERE 1 = 0")  # existe (si no, levantaría)
    c2.execute("SELECT codigo_sha256 FROM invitado WHERE id = 'inv-viejo'")
    assert c2.fetchone()[0] == "h"
    # Control negativo: en esta base de SQLite el `DROP NOT NULL` no se puede aplicar, así que el alta por correo FALLA en voz alta,
    # no en silencio. En Postgres lo aplica la migración.
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError):
        invitados.alta_por_correo(conn.cursor(), "colega@dominio.cr", "Colega", 2)
    conn.close()


def test_las_migraciones_son_idempotentes_y_cuadran_con_el_ddl_de_una_base_nueva():
    assert esquema_conector.MIGRACIONES
    for s in esquema_conector.MIGRACIONES:
        if s.startswith("UPDATE "):  # relleno de una columna nueva: idempotente por su cláusula WHERE sobre IS NULL
            assert "IS NULL" in s
            continue
        if " DROP NOT NULL" in s:  # v2: el alta por correo no genera código permanente, así que `codigo_sha256` deja de ser obligatorio
            assert "ALTER COLUMN codigo_sha256" in s
            invitado = next(d for d in esquema_conector.DDL if d.startswith("CREATE TABLE IF NOT EXISTS invitado "))
            assert "codigo_sha256 TEXT UNIQUE" in invitado and "codigo_sha256 TEXT NOT NULL" not in invitado  # y una base nueva ya nace nulable
            continue
        assert "ADD COLUMN IF NOT EXISTS" in s
        tabla, (columna, tipo) = s.split("ALTER TABLE ")[1].split()[0], s.split("IF NOT EXISTS ")[1].split()[:2]
        crear = next(d for d in esquema_conector.DDL if d.startswith(f"CREATE TABLE IF NOT EXISTS {tabla} "))
        assert f"{columna} {tipo}" in crear  # una base nueva nace con la columna que la migración agrega a una vieja
    assert "conector_consulta" in esquema_conector.TABLAS


def test_crear_esquema_con_migrar_corre_las_migraciones():
    ejecutadas = []

    class Falsa:
        def cursor(self):
            return type("Cur", (), {"execute": lambda _s, sql, *a: ejecutadas.append(sql)})()

        def commit(self):
            pass
    esquema_conector.crear_esquema(Falsa(), migrar=True)
    n_m, n_i = len(esquema_conector.MIGRACIONES), len(esquema_conector.INDICES)
    assert ejecutadas[-(n_m + n_i):-n_i] == list(esquema_conector.MIGRACIONES)  # las migraciones, y recién después los índices (necesitan las columnas)
    assert ejecutadas[-n_i:] == list(esquema_conector.INDICES)
    ejecutadas.clear()
    esquema_conector.crear_esquema(Falsa())  # SQLite: sin migraciones
    assert not set(esquema_conector.MIGRACIONES) & set(ejecutadas)

    # El script de esquema migra contra Postgres (cualquier conexión que no sea la SQLite de pruebas).
    spec = importlib.util.spec_from_file_location("conector_invitados", RAIZ / "scripts" / "conector_invitados.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    ejecutadas.clear()
    try:
        bd.usar(estado=Falsa)
        assert script.main(["esquema"]) == 0
    finally:
        bd.usar()
    assert set(esquema_conector.MIGRACIONES) <= set(ejecutadas)


def test_el_script_de_esquema_sobre_sqlite_no_migra_y_no_falla(estado_sqlite):
    spec = importlib.util.spec_from_file_location("conector_invitados", RAIZ / "scripts" / "conector_invitados.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    assert script.main(["esquema"]) == 0  # Sobre SQLite la base ya nace completa: no corre el ALTER que SQLite no entiende


# --- el informe -----------------------------------------------------------------------------------------------------------------

def _actividad():
    spec = importlib.util.spec_from_file_location("conector_actividad", RAIZ / "scripts" / "conector_actividad.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_el_informe_muestra_uso_por_invitado_y_las_consultas_sin_hashes(estado_sqlite):
    act = _actividad()
    inv, codigo = invitar("Colega Prueba")
    otro, _ = invitar("Colega Callado")
    t0 = int(cr("2026-11-10 08:30").timestamp())
    with bd.estado() as conn:
        cur = conn.cursor()
        for jti in ("j1", "j2"):
            cur.execute("INSERT INTO credencial (jti, invitado_id, client_id, creado_ts, expira_ts, aviso_version) "
                        "VALUES (%s, %s, %s, %s, %s, %s)", (jti, inv, "cli", t0, t0 + 999, 2))
    for ts, herramienta, resultado, ms in ((t0, "buscar", "ok", 1000), (t0 + 3600, "buscar", "ok", 3000),
                                           (t0 + 86400, "buscar", "error:base_no_disponible", 500), (t0 + 86400 + 60, "ficha", "ok", 200)):
        registro.registrar(ts, inv, herramienta, resultado, ms)
    registro.registrar_consulta(t0, inv, "buscar", "daño moral", {"anno": 2024, "despacho": None})
    registro.registrar_consulta(t0 + 86400 + 60, inv, "ficha", "sen-1-0001-0000001")

    with bd.estado() as conn:
        salida = "\n".join(act.informe(conn.cursor()))
    assert "Colega Prueba" in salida and "Colega Callado" in salida and otro in salida
    assert "sesiones (credenciales emitidas): 2" in salida
    assert "primera llamada: 2026-11-10 08:30" in salida and "última: 2026-11-11 08:31" in salida  # hora de Costa Rica
    assert "buscar 3, ficha 1" in salida
    assert "búsquedas por día: 2026-11-10 2, 2026-11-11 1" in salida
    assert "media 1.2 s, máxima 3.0 s" in salida
    assert "error:base_no_disponible 1" in salida
    with bd.estado() as conn:
        cur = conn.cursor()
        cur.execute("SELECT codigo_sha256 FROM invitado")
        hashes = [f[0] for f in cur.fetchall()]
        lineas = act.consultas(cur, int(cr("2026-11-12 09:00").timestamp()))
        solo_ficha = act.consultas(cur, int(cr("2026-11-12 09:00").timestamp()), dias=2)  # 2026-11-10 09:00 en adelante: solo la ficha
        de_otro = act.consultas(cur, int(cr("2026-11-12 09:00").timestamp()), invitado=otro)
    texto = "\n".join(lineas)
    assert "2026-11-10 08:30" in texto and "«daño moral»" in texto and "[anno=2024]" in texto and "Colega Prueba" in texto
    assert ": 2 " in lineas[0] and ": 1 " in solo_ficha[0] and "sen-1-0001-0000001" in "\n".join(solo_ficha)
    assert ": 0 " in de_otro[0]
    for h_ in hashes + [codigo, "j1", "j2"]:
        assert h_ not in salida and h_ not in texto
