from dataclasses import dataclass
import json

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
    initialize_amendments(db)


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


def initialize_amendments(db):
    with write_transaction(db):
        db.execute('''
            CREATE TABLE IF NOT EXISTS amendment_reports (
                amendment_id INTEGER PRIMARY KEY,
                task_id INTEGER NOT NULL REFERENCES task_catalog (task_id),
                old_report_id INTEGER NOT NULL REFERENCES review_reports (report_id),
                new_report_id INTEGER NOT NULL REFERENCES review_reports (report_id),
                old_front INTEGER NOT NULL REFERENCES accepted_pieces (acceptance_id),
                old_back INTEGER NOT NULL REFERENCES accepted_pieces (acceptance_id),
                new_front INTEGER NOT NULL REFERENCES accepted_pieces (acceptance_id),
                new_back INTEGER NOT NULL REFERENCES accepted_pieces (acceptance_id),
                old_front_revision INTEGER NOT NULL,
                old_back_revision INTEGER NOT NULL,
                new_front_revision INTEGER NOT NULL,
                new_back_revision INTEGER NOT NULL,
                added TEXT NOT NULL,
                removed TEXT NOT NULL,
                CHECK (old_report_id <> new_report_id)
            )
        ''')
        db.execute('''
            CREATE TABLE IF NOT EXISTS amendment_proofs (
                amendment_id INTEGER NOT NULL REFERENCES amendment_reports (amendment_id),
                slot INTEGER NOT NULL CHECK (slot IN (1, 2)),
                digest TEXT NOT NULL,
                PRIMARY KEY (amendment_id, slot)
            )
        ''')
        db.execute('''
            CREATE TABLE IF NOT EXISTS amendment_receipts (
                amendment_id INTEGER PRIMARY KEY
                    REFERENCES amendment_reports (amendment_id),
                task_id INTEGER NOT NULL REFERENCES task_catalog (task_id)
            )
        ''')


def save_amendment(db, task_id, old_report_id, new_report_id, acceptances,
                   revisions, proofs, added, removed, *, before_commit=None):
    (old_front, old_back), (new_front, new_back) = acceptances
    (old_front_rev, old_back_rev), (new_front_rev, new_back_rev) = revisions
    values = (
        task_id, old_report_id, new_report_id,
        old_front, old_back, new_front, new_back,
        old_front_rev, old_back_rev, new_front_rev, new_back_rev,
        json.dumps([list(pair) for pair in added], separators=(',', ':')),
        json.dumps([list(pair) for pair in removed], separators=(',', ':')),
    )
    with write_transaction(db):
        cursor = db.execute('''
            INSERT INTO amendment_reports (
                task_id, old_report_id, new_report_id,
                old_front, old_back, new_front, new_back,
                old_front_revision, old_back_revision,
                new_front_revision, new_back_revision, added, removed
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', values)
        amendment_id = cursor.lastrowid
        db.executemany('''
            INSERT INTO amendment_proofs (amendment_id, slot, digest) VALUES (?, ?, ?)
        ''', ((amendment_id, slot, digest) for slot, digest in sorted(proofs.items())))
        receipt = (amendment_id, task_id)
        db.execute('''
            INSERT INTO amendment_receipts (amendment_id, task_id) VALUES (?, ?)
        ''', receipt)
        if before_commit is not None:
            before_commit()
    return amendment_id, receipt


def read_amendment_row(db, amendment_id):
    require_key(amendment_id)
    row = db.execute('''
        SELECT a.task_id, a.old_report_id, a.new_report_id,
               a.old_front, a.old_back, a.new_front, a.new_back,
               a.old_front_revision, a.old_back_revision,
               a.new_front_revision, a.new_back_revision,
               a.added, a.removed, r.task_id
        FROM amendment_reports AS a
        JOIN amendment_receipts AS r USING (amendment_id)
        WHERE a.amendment_id = ?
    ''', (amendment_id,)).fetchone()
    if row is None:
        raise KeyError(amendment_id)
    proofs = db.execute('''
        SELECT slot, digest FROM amendment_proofs
        WHERE amendment_id = ? ORDER BY slot
    ''', (amendment_id,)).fetchall()
    return row, tuple((int(slot), digest) for slot, digest in proofs)
