"""Thin Postgres helper. One connection per process is plenty at this volume."""
import psycopg
from pgvector.psycopg import register_vector
from pathlib import Path
from ..config import DATABASE_URL

_conn = None


def conn():
    global _conn
    if _conn is None or _conn.closed:
        _conn = psycopg.connect(DATABASE_URL, autocommit=True)
        try:
            register_vector(_conn)
        except psycopg.ProgrammingError:
            pass  # vector extension not created yet; init_db() will create it
    return _conn


def init_db():
    sql = (Path(__file__).parent / "schema.sql").read_text()
    with conn().cursor() as cur:
        cur.execute(sql)
    print("schema applied")


def query(sql, params=None):
    with conn().cursor() as cur:
        cur.execute(sql, params or ())
        return cur.fetchall()


def execute(sql, params=None):
    with conn().cursor() as cur:
        cur.execute(sql, params or ())
        return cur.rowcount


def executemany(sql, rows):
    with conn().cursor() as cur:
        cur.executemany(sql, rows)
        return cur.rowcount
