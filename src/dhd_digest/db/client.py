"""Thin Postgres helper. One connection per process is plenty at this volume."""
import psycopg
from pgvector.psycopg import register_vector
from pathlib import Path
from ..config import DATABASE_URL

_conn = None


def conn():
    global _conn
    if _conn is None or _conn.closed or _conn.broken:
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


def _reconnecting(fn):
    """Neon (and most hosted Postgres) drops connections that sit idle, e.g.
    through a long embedding wait. These helpers are single autocommit
    statements, so on a dropped connection it's safe to reconnect and retry once."""
    def wrapper(*args, **kwargs):
        global _conn
        try:
            return fn(*args, **kwargs)
        except psycopg.OperationalError:
            if _conn is not None and not (_conn.closed or _conn.broken):
                raise                              # a real error, not a dead connection
            print("  database connection dropped; reconnecting")
            _conn = None
            return fn(*args, **kwargs)
    return wrapper


@_reconnecting
def query(sql, params=None):
    with conn().cursor() as cur:
        cur.execute(sql, params or ())
        return cur.fetchall()


@_reconnecting
def execute(sql, params=None):
    with conn().cursor() as cur:
        cur.execute(sql, params or ())
        return cur.rowcount


@_reconnecting
def executemany(sql, rows):
    with conn().cursor() as cur:
        cur.executemany(sql, rows)
        return cur.rowcount
