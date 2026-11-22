from dataclasses import dataclass

from database import require_key, write_transaction
from plan.rationals import rational_text


@dataclass(frozen=True)
class ReviewReceipt:
    report_id: int
    task_id: int


def initialize_review(db):
    with write_transaction(db):
        db.execute('''
            CREATE TABLE IF NOT EXISTS review_reports (
                report_id INTEGER PRIMARY KEY,
                task_id INTEGER NOT NULL REFERENCES task_catalog (task_id),
                front_id INTEGER NOT NULL REFERENCES accepted_pieces (acceptance_id),
                back_id INTEGER NOT NULL REFERENCES accepted_pieces (acceptance_id),
                front_crossings INTEGER NOT NULL CHECK (front_crossings >= 0),
                back_crossings INTEGER NOT NULL CHECK (back_crossings >= 0),
                seam_before TEXT NOT NULL,
                seam_after TEXT NOT NULL,
                seam_change TEXT NOT NULL,
                seam_crossings INTEGER NOT NULL CHECK (seam_crossings IN (0, 1)),
                total_crossings INTEGER NOT NULL,
                CHECK (front_id <> back_id),
                CHECK (total_crossings = front_crossings + back_crossings + seam_crossings)
            )
        ''')
        db.execute('''
            CREATE TABLE IF NOT EXISTS review_receipts (
                report_id INTEGER PRIMARY KEY REFERENCES review_reports (report_id),
                task_id INTEGER NOT NULL REFERENCES task_catalog (task_id)
            )
        ''')


def save_review(db, selection, seam, total, *, before_commit=None):
    task_id = selection.task.task_id
    front, back = selection.front, selection.back
    values = (
        task_id, front.acceptance_id, back.acceptance_id,
        front.piece.crossings, back.piece.crossings, rational_text(seam.before),
        rational_text(seam.after), rational_text(seam.change), seam.crossings, total,
    )
    with write_transaction(db):
        cursor = db.execute('''
            INSERT INTO review_reports (
                task_id, front_id, back_id, front_crossings, back_crossings,
                seam_before, seam_after, seam_change, seam_crossings, total_crossings
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', values)
        report_id = cursor.lastrowid
        receipt = ReviewReceipt(report_id, task_id)
        db.execute('''
            INSERT INTO review_receipts (report_id, task_id) VALUES (?, ?)
        ''', (receipt.report_id, receipt.task_id))
        if before_commit is not None:
            before_commit()
    return report_id, receipt


def read_review_rows(db, report_id):
    require_key(report_id)
    row = db.execute('''
        SELECT r.task_id, r.front_id, r.back_id, r.front_crossings, r.back_crossings,
               r.seam_before, r.seam_after, r.seam_change, r.seam_crossings,
               r.total_crossings, c.report_id, c.task_id
        FROM review_reports AS r JOIN review_receipts AS c USING (report_id)
        WHERE r.report_id = ?
    ''', (report_id,)).fetchone()
    if row is None:
        raise KeyError(report_id)
    return tuple(row[:-2]), ReviewReceipt(*row[-2:])
