"""Adaptador de Postgres del índice (pg8000, Python puro: corre igual en cualquier entorno).

Conexión por variables de entorno, sin credenciales en el código: `REPLICA_DB_SOCKET` (socket Unix de la base) o `REPLICA_DB_HOST`/`REPLICA_DB_PORT`; `REPLICA_DB_NAME`,
`REPLICA_DB_USER` y `REPLICA_DB_PASSWORD` (inyectada como secreto).
"""

from __future__ import annotations

import os

from src.indice.esquema import DDL


def conectar():
    """Conexión nueva, sin autocommit: cada mes es una transacción.

    Con `REPLICA_DB_INSTANCIA` (`proyecto:región:instancia`) usa el conector oficial de la base administrada: entra con las credenciales
    de Google y certificados efímeros, sin abrir redes autorizadas.
    """
    import pg8000.dbapi
    comunes = {"database": os.environ.get("REPLICA_DB_NAME", "replica"), "user": os.environ["REPLICA_DB_USER"],
               "password": os.environ["REPLICA_DB_PASSWORD"]}
    if os.environ.get("REPLICA_DB_INSTANCIA"):
        from google.cloud.sql.connector import Connector
        conector = Connector()
        conn = conector.connect(os.environ["REPLICA_DB_INSTANCIA"], "pg8000", user=comunes["user"],
                                password=comunes["password"], db=comunes["database"])
        conn._conector_cloudsql = conector  # vive mientras viva la conexión
        return conn
    if os.environ.get("REPLICA_DB_SOCKET"):
        return pg8000.dbapi.connect(unix_sock=os.environ["REPLICA_DB_SOCKET"], **comunes)
    return pg8000.dbapi.connect(host=os.environ["REPLICA_DB_HOST"], port=int(os.environ.get("REPLICA_DB_PORT", "5432")),
                                **comunes)


def crear_esquema(conn) -> None:
    cur = conn.cursor()
    cur.execute(DDL)
    conn.commit()
