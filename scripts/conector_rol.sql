-- Rol `conector` de la base: el único que usa el servicio expuesto a internet (mínimo privilegio).
--
-- Mínimo privilegio, sin superusuario:
--   * SELECT sobre las tablas de fallos que lee el núcleo (documentos, vectores) y NADA más sobre ellas;
--   * SELECT/INSERT/UPDATE/DELETE solo sobre las tablas del conector (src/conector/esquema_conector.py: TABLAS);
--   * `conector_consulta` (texto de las consultas): SELECT, INSERT y DELETE, sin UPDATE
--     (las filas no se reescriben; el DELETE es la purga de 90 días que hace cada inserción);
--   * nada de CREATE ni de COPY ... PROGRAM, y ninguna lectura de otras tablas de la base.
--
-- Se corre una sola vez, con el rol dueño de la base, DESPUÉS de `python scripts/conector_invitados.py esquema` (las tablas
-- tienen que existir). Este archivo no trae la contraseña: entra por la variable de psql `clave`, que es la MISMA que se guarda en el
-- secreto `db-password-conector` (ver scripts/deploy_conector.sh, paso 3):
--
--     psql -h <host de la base de datos> -U <rol dueño> -d replica -v clave="<la contraseña>" -f scripts/conector_rol.sql
--
-- Es idempotente: repetirlo reajusta los privilegios y la contraseña. El nombre de la base (`replica`) es el de REPLICA_DB_NAME.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'conector') THEN
        CREATE ROLE conector LOGIN;
    END IF;
END
$$;

ALTER ROLE conector WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD :'clave';

GRANT CONNECT ON DATABASE replica TO conector;
GRANT USAGE ON SCHEMA public TO conector;

-- Punto de partida limpio: si el rol tuvo algo de más antes, se quita.
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM conector;

-- Fallos de la base: solo lectura.
GRANT SELECT ON documentos, vectores TO conector;

-- Tablas del conector: lectura y escritura.
GRANT SELECT, INSERT, UPDATE, DELETE ON
    invitado, oauth_cliente, oauth_codigo, credencial, uso, conector_llamada, conector_reporte, presupuesto_voyage_consultas, codigo_correo
    TO conector;

-- Texto de las consultas (aviso v2): se inserta, se lee para el informe y se purga a los 90 días; nunca se reescribe.
GRANT SELECT, INSERT, DELETE ON conector_consulta TO conector;
