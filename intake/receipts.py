from dataclasses import dataclass

from database import require_key


@dataclass(frozen=True)
class AcceptanceReceipt:
    acceptance_id: int
    origin: str
    piece_id: int


def initialize_receipts(db):
    db.execute('''
        CREATE TABLE IF NOT EXISTS acceptance_receipts (
            acceptance_id INTEGER PRIMARY KEY REFERENCES accepted_pieces (acceptance_id),
            origin TEXT NOT NULL,
            piece_id INTEGER NOT NULL
        )
    ''')


def insert_receipt(db, acceptance_id, origin, piece_id):
    receipt = AcceptanceReceipt(acceptance_id, origin, piece_id)
    db.execute('''
        INSERT INTO acceptance_receipts (acceptance_id, origin, piece_id)
        VALUES (?, ?, ?)
    ''', (receipt.acceptance_id, receipt.origin, receipt.piece_id))
    return receipt


def get_receipt(db, acceptance_id):
    require_key(acceptance_id)
    row = db.execute('''
        SELECT origin, piece_id FROM acceptance_receipts WHERE acceptance_id = ?
    ''', (acceptance_id,)).fetchone()
    if row is None:
        raise KeyError(acceptance_id)
    return AcceptanceReceipt(acceptance_id, *row)
