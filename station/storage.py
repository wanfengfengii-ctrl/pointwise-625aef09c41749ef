from database import require_key, write_transaction
from plan.rationals import parse_rational, rational_text
from .pieces import StationPiece


def initialize_station(db):
    db.execute('''
        CREATE TABLE IF NOT EXISTS station_pieces (
            piece_id INTEGER PRIMARY KEY,
            origin TEXT NOT NULL,
            task_id INTEGER NOT NULL REFERENCES task_catalog (task_id),
            slot INTEGER NOT NULL CHECK (slot IN (1, 2)),
            revision_id INTEGER NOT NULL REFERENCES reading_revisions (revision_id),
            first_value TEXT NOT NULL,
            last_value TEXT NOT NULL,
            crossings INTEGER NOT NULL CHECK (crossings >= 0)
        )
    ''')


def save_piece(db, revision, first, last, crossings):
    fields = (
        revision.origin, revision.task_id, revision.slot, revision.revision_id,
        rational_text(first), rational_text(last), crossings,
    )
    with write_transaction(db):
        cursor = db.execute('''
            INSERT INTO station_pieces
                (origin, task_id, slot, revision_id, first_value, last_value, crossings)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', fields)
        piece_id = cursor.lastrowid
    return piece_id


def get_piece(db, piece_id):
    require_key(piece_id)
    row = db.execute('''
        SELECT origin, task_id, slot, revision_id, first_value, last_value, crossings
        FROM station_pieces WHERE piece_id = ?
    ''', (piece_id,)).fetchone()
    if row is None:
        raise KeyError(piece_id)
    origin, task_id, slot, revision_id, first, last, crossings = row
    return StationPiece(
        origin, piece_id, task_id, slot, revision_id,
        parse_rational(first), parse_rational(last), crossings,
    )
