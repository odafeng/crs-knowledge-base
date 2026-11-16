"""Connection pool. Failures to reach the database surface as 503 `unavailable` (see errors.py)."""

from collections.abc import Iterator

from fastapi import HTTPException, Request
from psycopg import Connection
from psycopg.rows import DictRow, dict_row
from psycopg_pool import ConnectionPool

type Conn = Connection[DictRow]


def open_pool(url: str) -> ConnectionPool[Conn]:
    # wait=False: the app starts even while the database is down, and /health reports it.
    pool = ConnectionPool(
        url,
        connection_class=Connection[DictRow],
        kwargs={"row_factory": dict_row, "autocommit": True},
        min_size=1,
        max_size=10,
        timeout=5,
        open=False,
    )
    pool.open(wait=False)
    return pool


def get_conn(request: Request) -> Iterator[Conn]:
    pool: ConnectionPool[Conn] | None = request.app.state.pool
    if pool is None:
        raise HTTPException(status_code=503, detail="Database is not configured")
    with pool.connection() as conn:
        yield conn
