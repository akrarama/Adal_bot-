import psycopg
from pgvector.psycopg import register_vector

from . import config


def connect() -> psycopg.Connection:
    conn = psycopg.connect(config.DATABASE_URL, autocommit=True)
    conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    register_vector(conn)
    return conn


def init_schema() -> None:
    with connect() as conn:
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS documents (
                id        SERIAL PRIMARY KEY,
                title     TEXT NOT NULL,
                url       TEXT,
                doc_type  TEXT NOT NULL DEFAULT 'other',  -- constitution | law | address | concept | other
                lang      TEXT,
                filename  TEXT UNIQUE
            );
            CREATE TABLE IF NOT EXISTS chunks (
                id        SERIAL PRIMARY KEY,
                doc_id    INT REFERENCES documents(id) ON DELETE CASCADE,
                section   TEXT,
                content   TEXT NOT NULL,
                embedding vector({config.EMBED_DIM})
            );
            CREATE INDEX IF NOT EXISTS chunks_emb_idx
                ON chunks USING hnsw (embedding vector_cosine_ops);
            CREATE TABLE IF NOT EXISTS query_log (
                id         SERIAL PRIMARY KEY,
                user_id    BIGINT,
                lang       TEXT,
                question   TEXT,
                answered   BOOLEAN,
                best_dist  REAL,
                created_at TIMESTAMPTZ DEFAULT now()
            );
            """
        )
