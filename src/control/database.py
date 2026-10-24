"""Bounded lock acquisition and payload-free transaction diagnostics."""
import logging
import os
import random
import sqlite3
import threading
import time

LOG = logging.getLogger('phyexp.control.database')


def busy(error):
    code = getattr(error, 'sqlite_errorcode', None)
    return (code is not None and code & 255 in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)) or any(
        text in str(error).lower() for text in ('database is locked', 'database table is locked', 'database is busy'))


def begin_write(db, timeout=30):
    # Only retry BEGIN: no application code has run and no side effect can repeat.
    started = time.monotonic()
    attempts = 0
    db.execute('PRAGMA busy_timeout=0')
    while True:
        attempts += 1
        try:
            db.execute('BEGIN IMMEDIATE')
            db.execute('PRAGMA busy_timeout=30000')
            return attempts
        except sqlite3.OperationalError as error:
            remaining = timeout - (time.monotonic() - started)
            if not busy(error) or remaining <= 0:
                error.database_begin_attempts = attempts
                raise
            time.sleep(min(remaining, random.uniform(.01, .1)))


def diagnostic(*, transaction, operation, write, started, acquired, attempts, error):
    ended = time.monotonic()
    wait = (acquired or ended) - started
    held = ended - acquired if acquired is not None else 0
    if isinstance(error, sqlite3.Error) or wait >= 1 or held >= 1:
        # Never log SQL, parameters, model text, credentials or exception messages.
        LOG.warning('control_transaction transaction=%s operation=%s pid=%s thread=%s write=%s '
                    'wait_ms=%d held_ms=%d attempts=%d outcome=%s sqlite_code=%s',
                    transaction, operation, os.getpid(), threading.get_ident(), write,
                    round(wait * 1000), round(held * 1000), getattr(error, 'database_begin_attempts', attempts),
                    type(error).__name__ if error else 'committed', getattr(error, 'sqlite_errorname', None))
