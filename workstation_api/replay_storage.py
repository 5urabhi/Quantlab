"""Read-only SQLite retry helpers for replay jobs."""
import sqlite3
from time import sleep

ATTEMPTS=3


def is_busy(exc):
    code=getattr(exc,"sqlite_errorcode",None)
    return (isinstance(code,int) and code&255 in (sqlite3.SQLITE_BUSY,sqlite3.SQLITE_LOCKED)
            or "database is locked" in str(exc).lower()
            or "database table is locked" in str(exc).lower())


def _read(db,sql,args,method):
    for attempt in range(ATTEMPTS):
        cursor=None
        try:
            cursor=db.execute(sql,args)
            return getattr(cursor,method)()
        except sqlite3.OperationalError as exc:
            if not is_busy(exc):
                raise
            if attempt==ATTEMPTS-1:
                raise RuntimeError("Market library remains busy after bounded read retries; "
                    "replay stopped without scoring lock failures as missing quotes. "
                    "Check WAL mode and competing local processes, then retry.") from exc
        finally:
            if cursor is not None:
                cursor.close()
        sleep(.15*(2**attempt))


def fetchone(db,sql,args=()):
    return _read(db,sql,args,"fetchone")


def fetchall(db,sql,args=()):
    return _read(db,sql,args,"fetchall")


def journal_mode():
    from contextlib import closing
    from . import advanced_options as ao
    try:
        with closing(ao._read_database()) as db:
            return str(fetchone(db,"PRAGMA journal_mode")[0]).lower()
    except sqlite3.OperationalError as exc:
        if "unable to open database file" in str(exc):
            return "unavailable"
        raise
