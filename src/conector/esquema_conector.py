"""DDL idempotente de las tablas del conector. Ninguna guarda el TEXTO de una consulta salvo `conector_consulta`.

`conector_consulta` guarda el texto de `buscar`, el id de `ficha` y la frase de
`verificar_cita` SOLO de credenciales que aceptaron el aviso v2, y se purga a los 90 días (registro.py). Para los
LOGS rige lo contrario: el texto de una consulta jamás va a los registros del servicio, ni en un mensaje de error; la tabla es el único lugar donde vive.

SQL en el subconjunto común de Postgres y SQLite (sin `now()`, sin tipos serie, tiempos en segundos UTC como BIGINT), para que
los tests corran el mismo SQL de producción sobre SQLite. `conector_reporte` es texto libre voluntario: lo escribe Claude al llamar
`reportar`, con la instrucción de no incluir la consulta ni documentos del caso.

Una base NUEVA nace con todas las columnas (`DDL`). Una base que ya existía en Postgres se pone al día con `MIGRACIONES`
(`ADD COLUMN IF NOT EXISTS`, que SQLite no entiende): `crear_esquema(conn, migrar=True)`, lo que corre
el script de administración de invitados (`esquema`).
"""

from __future__ import annotations

TABLAS = (
    "invitado", "oauth_cliente", "oauth_codigo", "credencial", "uso", "conector_llamada", "conector_reporte",
    "presupuesto_voyage_consultas", "conector_consulta", "codigo_correo",
)

DDL = (
    "CREATE TABLE IF NOT EXISTS invitado (id TEXT PRIMARY KEY, codigo_sha256 TEXT UNIQUE, etiqueta TEXT, "
    "activo BOOLEAN NOT NULL, creado_ts BIGINT NOT NULL, baja_ts BIGINT, origen TEXT, correo TEXT, "
    "acepta_promociones BOOLEAN, promociones_ts BIGINT, promociones_version INT, correo_verificado_ts BIGINT)",
    "CREATE TABLE IF NOT EXISTS oauth_cliente (client_id TEXT PRIMARY KEY, registro TEXT NOT NULL, etiqueta TEXT NOT NULL, "
    "ip_sha256 TEXT, creado_ts BIGINT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS oauth_codigo (codigo_sha256 TEXT PRIMARY KEY, client_id TEXT NOT NULL, invitado_id TEXT NOT NULL, "
    "redirect_uri TEXT NOT NULL, redirect_uri_explicita BOOLEAN NOT NULL, code_challenge TEXT NOT NULL, scopes TEXT NOT NULL, "
    "resource TEXT, expira_ts BIGINT NOT NULL, usado_ts BIGINT, jti_emitido TEXT, aviso_version INT)",
    "CREATE TABLE IF NOT EXISTS credencial (jti TEXT PRIMARY KEY, invitado_id TEXT NOT NULL, client_id TEXT NOT NULL, "
    "creado_ts BIGINT NOT NULL, expira_ts BIGINT NOT NULL, revocada_ts BIGINT, motivo TEXT, aviso_version INT)",
    "CREATE INDEX IF NOT EXISTS credencial_invitado ON credencial (invitado_id)",
    "CREATE TABLE IF NOT EXISTS uso (clave TEXT NOT NULL, ventana TEXT NOT NULL, unidades BIGINT NOT NULL, "
    "PRIMARY KEY (clave, ventana))",
    "CREATE TABLE IF NOT EXISTS conector_llamada (ts BIGINT NOT NULL, invitado_id TEXT, herramienta TEXT NOT NULL, "
    "resultado TEXT NOT NULL, duracion_ms INTEGER, n_resultados INTEGER, via TEXT, cliente TEXT, version TEXT)",
    "CREATE INDEX IF NOT EXISTS conector_llamada_ts ON conector_llamada (ts)",
    "CREATE TABLE IF NOT EXISTS conector_reporte (ts BIGINT NOT NULL, invitado_id TEXT, version TEXT, resumen TEXT NOT NULL, "
    "problema TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS presupuesto_voyage_consultas (mes TEXT PRIMARY KEY, tokens BIGINT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS conector_consulta (ts BIGINT NOT NULL, invitado_id TEXT, herramienta TEXT NOT NULL, "
    "texto TEXT NOT NULL, filtros TEXT)",
    "CREATE INDEX IF NOT EXISTS conector_consulta_ts ON conector_consulta (ts)",
    # v2: código de un solo uso por correo. Atado a (invitado, cliente OAuth), no a la solicitud; solo se guarda su HMAC.
    "CREATE TABLE IF NOT EXISTS codigo_correo (id TEXT PRIMARY KEY, invitado_id TEXT NOT NULL, client_id TEXT NOT NULL, "
    "codigo_hmac TEXT NOT NULL, vence_ts BIGINT NOT NULL, intentos INT NOT NULL, usado_ts BIGINT, creado_ts BIGINT NOT NULL)",
    "CREATE INDEX IF NOT EXISTS codigo_correo_invitado ON codigo_correo (invitado_id)",
)

# Columnas agregadas después de la primera versión del esquema. Solo Postgres (SQLite no acepta `ADD COLUMN IF NOT EXISTS`);
# idempotentes, así que repetirlas no hace nada. Rollback: el código viejo ignora estas columnas.
MIGRACIONES = (
    "ALTER TABLE oauth_codigo ADD COLUMN IF NOT EXISTS aviso_version INT",
    "ALTER TABLE credencial ADD COLUMN IF NOT EXISTS aviso_version INT",
    # Origen del invitado: día en que se generó el código y forma (manual o automático). Los invitados anteriores
    # se crearon todos a mano.
    "ALTER TABLE invitado ADD COLUMN IF NOT EXISTS origen TEXT",
    "UPDATE invitado SET origen = 'manual' WHERE origen IS NULL",
    # correo del invitado y su autorizacion para recibir promociones (módulo de contacto). Opcionales: los invitados de hoy quedan sin correo hasta que se les agregue.
    "ALTER TABLE invitado ADD COLUMN IF NOT EXISTS correo TEXT",
    "ALTER TABLE invitado ADD COLUMN IF NOT EXISTS acepta_promociones BOOLEAN",
    "ALTER TABLE invitado ADD COLUMN IF NOT EXISTS promociones_ts BIGINT",
    "ALTER TABLE invitado ADD COLUMN IF NOT EXISTS promociones_version INT",
    # v2 (21/11/2026): el alta por correo ya no genera un código permanente, así que `codigo_sha256` deja de ser obligatorio
    # (sin esto la fila no entra). Aditivo: la versión anterior del servicio sigue funcionando con el esquema nuevo.
    "ALTER TABLE invitado ALTER COLUMN codigo_sha256 DROP NOT NULL",
    "ALTER TABLE invitado ADD COLUMN IF NOT EXISTS correo_verificado_ts BIGINT",
)

# Después de las migraciones: el índice único del correo necesita que la columna ya exista (en una base vieja la crea `MIGRACIONES`).
INDICES = ("CREATE UNIQUE INDEX IF NOT EXISTS invitado_correo ON invitado (correo)",)


def crear_esquema(conn, migrar: bool = False) -> None:
    """Crea las tablas que falten y, con `migrar`, agrega las columnas nuevas a las existentes (Postgres). Idempotente; lo corre el
    equipo una vez por entorno con el rol dueño (el servicio no crea tablas)."""
    from src.conector import bd  # perezoso: este módulo se importa también desde scripts sin la configuración de la base

    cur = conn.cursor()
    for sentencia in DDL + (MIGRACIONES if migrar else ()):
        cur.execute(sentencia)
    # El índice único va DESPUÉS de crear las tablas y migrar: con `migrar` (Postgres, ya con la columna) o en una base de SQLite que ya tiene la columna
    # `correo`. En una base vieja de SQLite sin migrar la columna puede no existir y el índice fallaría. (Si se evaluara antes del DDL, una base NUEVA
    # nunca tendría el índice: ese fue un error de la primera versión de este cambio.)
    con_indice = migrar
    if not migrar and bd.es_sqlite(conn):
        cur.execute("PRAGMA table_info(invitado)")
        con_indice = "correo" in {f[1] for f in cur.fetchall()}
    for sentencia in INDICES if con_indice else ():
        cur.execute(sentencia)
    conn.commit()
