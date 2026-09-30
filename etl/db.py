"""Database connection for the Weaving weaving analytics database.

One place decides where the database lives. On the factory PC that is a local
PostgreSQL service; from another desk on the department LAN it is the same
service reached by host name. Nothing else in the codebase knows a host, a
port or a password.

Settings come from the environment, with defaults that work on the machine the
database runs on:

    WEAVING_DB_HOST   default 'localhost'
    WEAVING_DB_PORT   default 5432
    WEAVING_DB_NAME   default 'weaving_db'
    WEAVING_DB_USER   default 'weaving'
    WEAVING_DB_PASS   default ''          (trust authentication on the LAN)

On a Windows factory PC these are set once in a .env file next to the app, or
as system environment variables, and never touched again.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

import psycopg2
import psycopg2.extras

SCHEMA = "weaving"


def _load_dotenv() -> None:
    """Read a .env sitting beside the project, if there is one.

    Deliberately tiny and dependency-free: the factory PC should not need a
    package installed for the dashboard to find its database.
    """
    for folder in (Path.cwd(), Path(__file__).resolve().parent.parent):
        env = folder / ".env"
        if not env.is_file():
            continue
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
        return


_load_dotenv()


def dsn() -> dict:
    return dict(
        host=os.environ.get("WEAVING_DB_HOST", "localhost"),
        port=int(os.environ.get("WEAVING_DB_PORT", "5432")),
        dbname=os.environ.get("WEAVING_DB_NAME", "weaving_db"),
        user=os.environ.get("WEAVING_DB_USER", "weaving"),
        password=os.environ.get("WEAVING_DB_PASS", ""),
    )


def describe() -> str:
    d = dsn()
    return f"{d['user']}@{d['host']}:{d['port']}/{d['dbname']}"


def connect(autocommit: bool = False):
    conn = psycopg2.connect(**dsn())
    conn.autocommit = autocommit
    with conn.cursor() as cur:
        cur.execute(f"SET search_path TO {SCHEMA}, public")
    if not autocommit:
        conn.commit()
    return conn


@contextmanager
def cursor(conn=None, dict_rows: bool = False):
    """Yield a cursor, committing on success and rolling back on failure.

    A load that fails half way leaves the database exactly as it was. There is
    no state in which the dashboard shows half a day.
    """
    own = conn is None
    conn = conn or connect()
    factory = psycopg2.extras.RealDictCursor if dict_rows else None
    cur = conn.cursor(cursor_factory=factory)
    try:
        yield cur
        if own:
            conn.commit()
    except Exception:
        if own:
            conn.rollback()
        raise
    finally:
        cur.close()
        if own:
            conn.close()
