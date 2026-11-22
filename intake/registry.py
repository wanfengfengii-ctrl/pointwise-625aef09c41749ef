from dataclasses import dataclass

from database import require_key, write_transaction
from station.evidence import SegmentCommitment, decode_commitment
from station.pieces import StationPiece
from .commitment import check_commitment
from .decode import decode_v1
from .eligibility import check_eligibility
from .receipts import AcceptanceReceipt, get_receipt, initialize_receipts, insert_receipt


@dataclass(frozen=True)
class AcceptedPiece:
    acceptance_id: int
    piece: StationPiece
    payload: bytes
    receipt: AcceptanceReceipt
    commitment: SegmentCommitment | None = None


@dataclass(frozen=True)
class CommittedPiece:
    acceptance_id: int
    piece: StationPiece
    payload: bytes
    receipt: AcceptanceReceipt
    commitment: SegmentCommitment
    commitment_payload: bytes


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
        db.execute('''
            CREATE TABLE IF NOT EXISTS accepted_commitments (
                acceptance_id INTEGER PRIMARY KEY
                    REFERENCES accepted_pieces (acceptance_id),
                payload BLOB NOT NULL
            )
        ''')
        initialize_receipts(db)


def _read_row(db, origin, piece_id):
    return db.execute('''
        SELECT acceptance_id, payload FROM accepted_pieces
        WHERE origin = ? AND piece_id = ?
    ''', (origin, piece_id)).fetchone()


def _read_commitment(db, acceptance_id):
    row = db.execute('''
        SELECT payload FROM accepted_commitments WHERE acceptance_id = ?
    ''', (acceptance_id,)).fetchone()
    if row is None:
        return None
    return row[0]


def accept_segment(db, payload):
    piece = decode_v1(payload)
    check_eligibility(db, piece)
    with write_transaction(db):
        previous = _read_row(db, piece.origin, piece.piece_id)
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


def accept_committed_segment(db, payload, commitment):
    """Lock the original piece and its commitment in one first intake."""
    piece = decode_v1(payload)
    document = decode_commitment(commitment)
    check_eligibility(db, piece)
    check_commitment(db, piece, document)
    with write_transaction(db):
        previous = _read_row(db, piece.origin, piece.piece_id)
        if previous is not None:
            acceptance_id, original = previous
            if piece != decode_v1(original):
                raise ValueError('station piece identity already has different content')
            stored = _read_commitment(db, acceptance_id)
            if stored is None:
                raise ValueError('a piece accepted under plain V1 cannot gain a commitment')
            if decode_commitment(stored) != document:
                raise ValueError('station piece identity already has a different commitment')
            return acceptance_id

        cursor = db.execute('''
            INSERT INTO accepted_pieces (origin, piece_id, payload) VALUES (?, ?, ?)
        ''', (piece.origin, piece.piece_id, payload))
        acceptance_id = cursor.lastrowid
        db.execute('''
            INSERT INTO accepted_commitments (acceptance_id, payload) VALUES (?, ?)
        ''', (acceptance_id, commitment))
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
    committed = _read_commitment(db, acceptance_id)
    commitment = None if committed is None else decode_commitment(committed)
    return AcceptedPiece(
        acceptance_id, decode_v1(payload), payload,
        get_receipt(db, acceptance_id), commitment,
    )


def get_committed_piece(db, acceptance_id):
    accepted = get_accepted_piece(db, acceptance_id)
    if accepted.commitment is None:
        raise ValueError('acceptance has no first-intake commitment')
    return CommittedPiece(
        accepted.acceptance_id, accepted.piece, accepted.payload, accepted.receipt,
        accepted.commitment, _read_commitment(db, acceptance_id),
    )
