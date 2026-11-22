from dataclasses import dataclass

from database import require_key, write_transaction
from station.pieces import StationPiece
from .decode import decode_v1
from .eligibility import check_eligibility
from .receipts import AcceptanceReceipt, get_receipt, initialize_receipts, insert_receipt


@dataclass(frozen=True)
class AcceptedPiece:
    acceptance_id: int
    piece: StationPiece
    payload: bytes
    receipt: AcceptanceReceipt


def initialize_intake(db):
    with write_transaction(db):
        db.execute('''
            CREATE TABLE IF NOT EXISTS accepted_pieces (
                acceptance_id INTEGER PRIMARY KEY,
                origin TEXT NOT NULL,
                piece_id INTEGER NOT NULL,
                payload BLOB NOT NULL,
                UNIQUE (origin, piece_id)
            )
        ''')
        initialize_receipts(db)


def accept_segment(db, payload):
    piece = decode_v1(payload)
    check_eligibility(db, piece)
    with write_transaction(db):
        previous = db.execute('''
            SELECT acceptance_id, payload FROM accepted_pieces
            WHERE origin = ? AND piece_id = ?
        ''', (piece.origin, piece.piece_id)).fetchone()
        if previous is not None:
            acceptance_id, original = previous
            if piece != decode_v1(original):
                raise ValueError('station piece identity already has different content')
            return acceptance_id

        cursor = db.execute('''
            INSERT INTO accepted_pieces (origin, piece_id, payload) VALUES (?, ?, ?)
        ''', (piece.origin, piece.piece_id, payload))
        acceptance_id = cursor.lastrowid
        insert_receipt(db, acceptance_id, piece.origin, piece.piece_id)
    return acceptance_id


def get_accepted_piece(db, acceptance_id):
    require_key(acceptance_id)
    row = db.execute('''
        SELECT payload FROM accepted_pieces WHERE acceptance_id = ?
    ''', (acceptance_id,)).fetchone()
    if row is None:
        raise KeyError(acceptance_id)
    payload = row[0]
    return AcceptedPiece(acceptance_id, decode_v1(payload), payload, get_receipt(db, acceptance_id))
