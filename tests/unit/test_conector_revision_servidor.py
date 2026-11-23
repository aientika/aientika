"""Correcciones en el servidor y el despliegue: autenticación, compuerta de token sin verificar, sesiones, configuración, permisos de base y las bajas de configuración.

Cada test falla sin su corrección. Uno de ellos es el detector de la compuerta «token sin verificar ⇒ no se toca ningún dato»:
falla si la compuerta se quita.
"""

import asyncio
import re
import threading
from pathlib import Path

import pytest
from conector_apoyo import pkce, volcar_tablas
from test_conector_oauth import autorizar, flujo_completo
from test_conector_servidor import texto_de_herramienta
from test_indice_tope_voyage import AHORA, Objetos

from src.conector import bd, esquema_conector, oauth, pantalla, presupuesto_voyage as P, servidor as S, voyage_consulta as VC
from src.indice import tope_voyage as T

RAIZ = Path(__file__).resolve().parents[2]
DEPLOY = (RAIZ / "scripts" / "deploy_conector.sh").read_text(encoding="utf-8")
ROL_SQL = (RAIZ / "scripts" / "conector_rol.sql").read_text(encoding="utf-8")


# --- autenticación -------------------------------------------------------------------------------------------------------------------------

def filas_de_uso(ruta, prefijo):
    return [f for f in volcar_tablas(ruta).split("\n") if f.startswith("uso:")][0].count(prefijo)


def test_una_ip_ya_bloqueada_no_consume_el_contador_global(servidor_http):
    c, ruta = servidor_http
    challenge = pkce()[1]
    for _ in range(pantalla.INTENTOS_POR_IP):
        assert autorizar(c, "BBBB-BBBB-BBBB-BBBB", challenge)[1].status_code == 401
    for _ in range(5):  # la IP está agotada: estos POST no deben seguir gastando el global de todos
        assert autorizar(c, "BBBB-BBBB-BBBB-BBBB", challenge)[1].status_code == 429
    with bd.estado() as conn:
        cur = conn.cursor()
        cur.execute("SELECT unidades FROM uso WHERE clave = %s", ("intento-global",))
        assert cur.fetchone()[0] == pantalla.INTENTOS_POR_IP  # control positivo: los intentos válidos sí cuentan


def test_baja3_la_ip_del_intento_se_guarda_hasheada(servidor_http):
    c, ruta = servidor_http
    autorizar(c, "BBBB-BBBB-BBBB-BBBB", pkce()[1])
    volcado = volcar_tablas(ruta)
    assert "intento-ip:" in volcado and "testclient" not in volcado.split("intento-ip:")[1][:80]
    assert f"intento-ip:{oauth.hash_ip('testclient')}" in volcado


# --- compuerta de token sin verificar -------------------------------------------------------------------------------------------------------------------------

def test_con_el_token_sin_verificar_no_se_toca_ningun_dato(servidor_http, monkeypatch):
    """Un invitado dado de baja cuya credencial no se pudo cotejar (la base falló justo ahí) NO recibe datos aunque la base vuelva."""
    c, ruta = servidor_http
    token, *_ = flujo_completo(c)
    lecturas = []
    bd.usar(estado=bd.fabrica_sqlite(ruta), lectura=lambda: lecturas.append(1) or (_ for _ in ()).throw(OSError("la base no responde")))

    def sin_cotejar(self, jti, invitado):
        raise bd.BDNoDisponible("too many connections")
    monkeypatch.setattr(oauth.ProveedorConector, "_credencial_vigente", sin_cotejar)
    antes = volcar_tablas(ruta)
    for nombre, args in (("buscar", {"consulta": "responsabilidad"}), ("ficha", {"id": "x"}), ("ayuda", {}),
                         ("verificar_cita", {"id": "x", "frase": "una frase suficientemente larga"})):
        r = texto_de_herramienta(c, token, nombre, args)
        assert r["error"] == "base_no_disponible" and "resultados" not in r, (nombre, r)
    assert lecturas == [] and volcar_tablas(ruta) == antes  # ni la base ni los contadores se tocaron


def test_control_positivo_con_el_token_verificado_la_herramienta_si_llega_a_la_base(servidor_http):
    c, ruta = servidor_http
    token, *_ = flujo_completo(c)
    lecturas = []
    bd.usar(estado=bd.fabrica_sqlite(ruta), lectura=lambda: lecturas.append(1) or (_ for _ in ()).throw(OSError("la base no responde")))
    assert texto_de_herramienta(c, token, "buscar", {"consulta": "responsabilidad"})["error"] == "base_no_disponible"
    assert lecturas  # sin esta prueba, el test de arriba podría pasar porque nada llega nunca a la base


# --- sesiones -------------------------------------------------------------------------------------------------------------------------

def test_embebido_mas_consultas_nunca_pasan_del_techo_de_la_cuenta():
    assert T.TOPE_EMBEBIDO_USD + P.TOPE_USD_MES == T.TOPE_USD
    assert P.TOPE_USD_MES == T.RESERVA_CONSULTAS_USD


def _libro_en(usd):
    import json
    o = Objetos()
    o.datos[f"{T.PREFIJO}/2026-11.json"] = (json.dumps({"usd": usd, "tokens": 0}).encode(), 1)
    return T.TopeVoyage(o, AHORA)


def test_el_libro_de_gasto_corta_el_embebido_en_tope_menos_reserva(monkeypatch):
    monkeypatch.setenv("VOYAGE_OPT_OUT_CONFIRMADO", "2026-11-07")
    tope = _libro_en(T.tope_embebido("2026-11") - 0.0001)
    assert tope.tope_del_mes("2026-11") == T.tope_embebido("2026-11") < T.tope_cuenta("2026-11")
    with pytest.raises(T.TopeAlcanzado):  # pasa del corte del embebido aunque estaría por debajo del techo de la cuenta
        tope.reservar("voyage-4", ["x" * 100_000])


def test_control_positivo_bajo_el_corte_del_embebido_si_reserva(monkeypatch):
    monkeypatch.setenv("VOYAGE_OPT_OUT_CONFIRMADO", "2026-11-07")
    tope = _libro_en(T.tope_embebido("2026-11") - 1.0)
    tope.reservar("voyage-4", ["x" * 100_000])  # no debe lanzar TopeAlcanzado


# --- configuración -------------------------------------------------------------------------------------------------------------------------

def test_la_consulta_a_voyage_no_espera_los_300_segundos_del_embebido_por_lotes(monkeypatch):
    vistos = {}

    class Falso:
        def __init__(self, clave, **kw):
            vistos.update(kw)

        def embeber(self, textos, modelo, tipo="document"):
            return [[0.0] * 1024], 3

    monkeypatch.setattr(VC, "ClienteVoyage", Falso)
    monkeypatch.setenv("VOYAGE_API_KEY", "k" * 10)
    monkeypatch.setenv("VOYAGE_OPT_OUT_CONFIRMADO", "2026-11-07")
    VC.embeber_consulta("responsabilidad civil", reservar=lambda t: None)
    assert vistos["timeout"] == VC.TIEMPO_MAXIMO_S and VC.TIEMPO_MAXIMO_S <= 15


def test_el_servidor_usa_un_ejecutor_propio_dimensionado():
    async def correr():
        ejecutor = S.usar_ejecutor_propio(asyncio.get_running_loop())
        nombre = await asyncio.to_thread(lambda: threading.current_thread().name)
        return ejecutor._max_workers, nombre
    hilos, nombre = asyncio.run(correr())
    assert hilos == S.HILOS and S.HILOS >= 16 and nombre.startswith("conector")


def test_la_concurrencia_de_cloud_run_no_pasa_de_los_hilos():
    assert int(re.search(r"^HILOS=(\d+)", DEPLOY, re.M).group(1)) == S.HILOS and "--concurrency=${HILOS}" in DEPLOY


# --- permisos de base -------------------------------------------------------------------------------------------------------------------------

def test_el_deploy_no_usa_postgres_y_toma_el_usuario_de_una_variable():
    assert 'BD_USUARIO="${BD_USUARIO:-conector}"' in DEPLOY and "REPLICA_DB_USER=${BD_USUARIO}" in DEPLOY
    assert not re.search(r"REPLICA_DB_USER=postgres|DB_USER=postgres", DEPLOY)
    assert 'SECRETO_BD="db-password-conector"' in DEPLOY and "gcloud secrets create ${SECRETO_BD}" in DEPLOY
    assert not re.search(r"^\s*gcloud ", DEPLOY, re.M)  # el script solo imprime


def test_el_rol_es_de_minimo_privilegio():
    sql = re.sub(r"--[^\n]*", "", ROL_SQL)
    assert re.search(r"NOSUPERUSER", sql) and not re.search(r"(?<!NO)SUPERUSER", sql) and "NOCREATEROLE" in sql and "BYPASSRLS" in sql
    assert "ALL PRIVILEGES" not in sql and "OWNER" not in sql.upper().replace("NOSUPERUSER", "") and "PASSWORD :'clave'" in sql
    escritura = re.search(r"GRANT SELECT, INSERT, UPDATE, DELETE ON\s+(.+?)\s+TO conector", sql, re.S).group(1)
    consultas = re.search(r"GRANT SELECT, INSERT, DELETE ON\s+(.+?)\s+TO conector", sql, re.S).group(1)
    # exactamente las del conector; el texto de las consultas sin UPDATE
    assert {t.strip() for t in escritura.split(",")} | {consultas.strip()} == set(esquema_conector.TABLAS)
    assert consultas.strip() == "conector_consulta" and "conector_consulta" not in escritura
    lectura = re.search(r"GRANT SELECT ON\s+(.+?)\s+TO conector", sql, re.S).group(1)
    assert {t.strip() for t in lectura.split(",")} == {"documentos", "vectores"}
    assert not re.search(r"PASSWORD\s+'", sql)  # la contraseña entra por la variable, nunca escrita en el repo


def test_el_rol_cubre_toda_tabla_que_el_codigo_lee_o_escribe():
    """Si un módulo empieza a usar una tabla nueva y nadie ajusta el rol, el servicio falla en silencio con `permission denied`."""
    usadas = set()
    for f in (RAIZ / "src" / "conector").glob("*.py"):
        usadas |= set(re.findall(r"\b(?:FROM|JOIN|INTO|UPDATE)\s+([a-z_]+)\b", f.read_text(encoding="utf-8")))
    usadas -= {"set", "q", "c", "x", "uno", "condicional"}  # `DO UPDATE SET`, alias de CTE y "UPDATE condicional" de un docstring
    usadas -= {"fecha"}  # `extract(year FROM fecha)` en cobertura.despachos: es una columna, no una tabla
    otorgadas = set(esquema_conector.TABLAS) | {"documentos", "vectores"}
    assert {"documentos", "vectores", "uso", "credencial"} <= usadas  # control positivo: el escaneo encuentra tablas
    assert usadas <= otorgadas, usadas - otorgadas


# --- bajas de configuración ---------------------------------------------------------------------------------------------------------------------

def test_baja6_en_cloud_run_la_url_publica_debe_ser_https():
    with pytest.raises(S.ConfiguracionInvalida, match="https"):
        S.Configuracion(url_publica="http://localhost:8080", en_cloud_run=True).validar()
    S.Configuracion(url_publica="https://x.run.app", en_cloud_run=True).validar()  # control positivo
    S.Configuracion(url_publica="http://localhost:8080").validar()  # en desarrollo local sigue valiendo
