from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from database import connect
from intake.registry import accept_segment, initialize_intake
from ledger.ingest import record_segment
from ledger.storage import initialize_ledger
from plan.catalog import get_task, initialize_catalog, install_task_snapshot
from plan.layout import SegmentLayout
from plan.tasks import open_task
from review.storage import initialize_review
from station.export import export_segment
from station.freeze import freeze_segment
from station.storage import initialize_station


WEST = 'west'
EAST = 'east'


class FailBeforeCommit:
    def __init__(self, observe):
        self.observe = observe
        self.error = sqlite3.OperationalError('fixture interrupted the pending write transaction')
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if self.calls == 1:
            self.observe()
            raise self.error


def task_layout(front=(0, 1), back=(2, 3), back_origin=EAST):
    return (
        SegmentLayout(1, WEST, 'front-rig', front),
        SegmentLayout(2, back_origin, 'back-rig', back),
    )


class LabCase(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory(prefix='yuwan-test-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.center = self.open_db('center')
        self.left = self.open_db(WEST)
        self.right = self.open_db(EAST)
        self.init_center(self.center)
        self.init_station(self.left, WEST)
        self.init_station(self.right, EAST)

    def open_db(self, name):
        db = connect(self.root / f'{name}.sqlite')
        self.addCleanup(db.close)
        return db

    def init_center(self, db):
        initialize_catalog(db)
        initialize_intake(db)
        initialize_review(db)

    def init_station(self, db, origin):
        initialize_catalog(db)
        initialize_ledger(db, origin)
        initialize_station(db)

    def new_task(self, front=(0, 1), back=(2, 3), *, threshold=1, limit=1, back_origin=EAST, name='Compression'):
        number = open_task(self.center, name, 'kN', threshold, limit, task_layout(front, back, back_origin))
        snapshot = get_task(self.center, number)
        install_task_snapshot(self.left, snapshot)
        install_task_snapshot(self.right, snapshot)
        return number

    def send(self, db, revision):
        piece_id = freeze_segment(db, revision)
        return accept_segment(self.center, export_segment(db, piece_id))

    def offline_pieces(self, task_id, front, back):
        first = record_segment(self.left, task_id, 1, front)
        second = record_segment(self.right, task_id, 2, back)
        front_wire = export_segment(self.left, freeze_segment(self.left, first))
        back_wire = export_segment(self.right, freeze_segment(self.right, second))
        self.left.close()
        self.right.close()
        return accept_segment(self.center, front_wire), accept_segment(self.center, back_wire)

    def review_counts(self, db=None):
        if db is None:
            db = self.center
        reports = db.execute('SELECT count(*) FROM review_reports').fetchone()[0]
        receipts = db.execute('SELECT count(*) FROM review_receipts').fetchone()[0]
        return reports, receipts

    def revision_counts(self, db=None):
        if db is None:
            db = self.left
        revisions = db.execute('SELECT count(*) FROM reading_revisions').fetchone()[0]
        samples = db.execute('SELECT count(*) FROM reading_samples').fetchone()[0]
        return revisions, samples

    def intake_counts(self):
        pieces = self.center.execute('SELECT count(*) FROM accepted_pieces').fetchone()[0]
        receipts = self.center.execute('SELECT count(*) FROM acceptance_receipts').fetchone()[0]
        return pieces, receipts
