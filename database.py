from contextlib import contextmanager
import sqlite3


_MAX_SQLITE_ID = (1 << 63) - 1


def connect(path):
    db = sqlite3.connect(path, isolation_level=None)
    db.execute('PRAGMA foreign_keys = ON')
    return db


def is_key(value):
    return type(value) is int and 0 < value <= _MAX_SQLITE_ID


def require_key(value):
    if not is_key(value):
        raise KeyError(value)


@contextmanager
def write_transaction(db):
    """Own the write transaction, including the read before replay detection."""
    if db.in_transaction:
        raise sqlite3.ProgrammingError('a write operation requires an idle connection')
    db.execute('BEGIN IMMEDIATE')
    try:
        yield
        db.commit()
    except BaseException as error:
        if db.in_transaction:
            try:
                db.rollback()
            except sqlite3.Error as rollback_error:
                error.add_note(f'rollback also failed: {rollback_error}')
        raise
