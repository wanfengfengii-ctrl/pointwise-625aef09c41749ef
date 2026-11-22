from database import require_key, write_transaction
from plan.protocols import require_label
from plan.rationals import parse_rational, rational_text


def initialize_ledger(db, origin):
    require_label(origin, 'station origin')
    with write_transaction(db):
        db.execute('''
            CREATE TABLE IF NOT EXISTS ledger_site (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                origin TEXT NOT NULL
            )
        ''')
        row = db.execute('SELECT origin FROM ledger_site WHERE singleton = 1').fetchone()
        if row is None:
            db.execute('INSERT INTO ledger_site VALUES (1, ?)', (origin,))
        elif row[0] != origin:
            raise ValueError('station database is already bound to another origin')

        db.execute('''
            CREATE TABLE IF NOT EXISTS reading_revisions (
                revision_id INTEGER PRIMARY KEY,
                task_id INTEGER NOT NULL REFERENCES task_catalog (task_id),
                slot INTEGER NOT NULL CHECK (slot IN (1, 2)),
                origin TEXT NOT NULL,
                rig TEXT NOT NULL,
                parent_id INTEGER REFERENCES reading_revisions (revision_id)
            )
        ''')
        db.execute('''
            CREATE TABLE IF NOT EXISTS reading_samples (
                revision_id INTEGER NOT NULL REFERENCES reading_revisions (revision_id),
                ordinal INTEGER NOT NULL,
                beat TEXT NOT NULL,
                value TEXT NOT NULL,
                PRIMARY KEY (revision_id, ordinal),
                UNIQUE (revision_id, beat)
            )
        ''')


def ledger_origin(db):
    row = db.execute('SELECT origin FROM ledger_site WHERE singleton = 1').fetchone()
    if row is None:
        raise ValueError('station database has no bound origin')
    return row[0]


def insert_revision(db, task_id, layout, samples, parent_id):
    with write_transaction(db):
        cursor = db.execute('''
            INSERT INTO reading_revisions (task_id, slot, origin, rig, parent_id)
            VALUES (?, ?, ?, ?, ?)
        ''', (task_id, layout.slot, layout.origin, layout.rig, parent_id))
        revision_id = cursor.lastrowid
        db.executemany('''
            INSERT INTO reading_samples (revision_id, ordinal, beat, value)
            VALUES (?, ?, ?, ?)
        ''', (
            (revision_id, ordinal, str(beat), rational_text(value))
            for ordinal, (beat, value) in enumerate(samples)
        ))
    return revision_id


def read_revision_header(db, revision_id):
    require_key(revision_id)
    row = db.execute('''
        SELECT task_id, slot, origin, rig, parent_id
        FROM reading_revisions WHERE revision_id = ?
    ''', (revision_id,)).fetchone()
    if row is None:
        raise KeyError(revision_id)
    return tuple(row)


def read_revision_samples(db, revision_id):
    require_key(revision_id)
    rows = db.execute('''
        SELECT beat, value FROM reading_samples
        WHERE revision_id = ? ORDER BY ordinal
    ''', (revision_id,))
    return tuple((int(beat), parse_rational(value)) for beat, value in rows)
