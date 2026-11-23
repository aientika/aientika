"""Esquema de la base del índice. Idempotente: se puede correr varias veces.

El texto se guarda TAL CUAL viene de la fuente, con su hash. El `tsvector` se arma con el texto
normalizado al vuelo (`extracto.normalizar`) y sin posiciones (`strip`): la preselección es un AND de términos y la frase se
confirma después sobre el texto. Los vectores van en una tabla aparte, una fila por documento y modelo.
"""

DDL = """
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS vector;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_ts_config WHERE cfgname = 'replica_simple') THEN
    CREATE TEXT SEARCH CONFIGURATION replica_simple (COPY = simple);
    ALTER TEXT SEARCH CONFIGURATION replica_simple
      ALTER MAPPING FOR hword, hword_part, word WITH unaccent, simple;
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS documentos (
  id_documento      text PRIMARY KEY,
  despacho          text NOT NULL,
  anno              int  NOT NULL,
  mes               int  NOT NULL CHECK (mes BETWEEN 1 AND 12),
  tipo              text NOT NULL,            -- SNT o EXT
  numero            text,
  numero_padre      text,
  fecha             date,
  expediente        text,
  redactor_metadato text,                     -- metadato del índice de origen: NO sirve para citar
  descriptores      jsonb,
  clase_f2          text,                     -- embeber / rechazo_formal / ejecucion / sin_por_tanto (solo SNT)
  texto             text NOT NULL,
  hash_sha256       text NOT NULL,
  tsv               tsvector NOT NULL,
  cargado_en        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS documentos_tsv ON documentos USING gin (tsv);
CREATE INDEX IF NOT EXISTS documentos_despacho_anno_mes ON documentos (despacho, anno, mes);

CREATE TABLE IF NOT EXISTS vectores (
  id_documento text NOT NULL REFERENCES documentos (id_documento) ON DELETE CASCADE,
  modelo       text NOT NULL,
  trozo        int  NOT NULL DEFAULT 0,       -- 0 = extracto entero
  dimension    int  NOT NULL,
  vector       halfvec NOT NULL,
  recortado    boolean NOT NULL DEFAULT false,
  PRIMARY KEY (id_documento, modelo, trozo)
);

"""
