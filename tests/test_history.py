from intake.registry import get_accepted_piece
from ledger.ingest import record_segment
from ledger.query import get_revision
from plan.catalog import get_task
from review.history import get_review
from review.issue import issue_review
from station.export import export_segment
from station.freeze import freeze_segment
from station.storage import get_piece
from tests.fixtures import EAST, WEST, LabCase


class TestHistory(LabCase):
    def test_correction_keeps_original_review(self):
        task = self.new_task()
        front = self.send(self.left, record_segment(self.left, task, 1, [(0, 0), (1, 0)]))
        original_revision = record_segment(self.right, task, 2, [(2, 1), (3, 1)])
        original_back = self.send(self.right, original_revision)
        self.left.close()
        self.right.close()
        old_id, old_receipt = issue_review(self.center, task, front, original_back)

        station = self.open_db(EAST)
        corrected = record_segment(station, task, 2, [(2, 0), (3, 0)], parent_id=original_revision)
        new_back = self.send(station, corrected)
        station.close()
        new_id, new_receipt = issue_review(self.center, task, front, new_back)
        self.assertNotEqual(old_id, new_id)
        self.assertNotEqual(original_back, new_back)
        self.center.close()
        self.center = self.open_db('center')

        for number, receipt, back, last, count in (
            (old_id, old_receipt, original_back, 1, 1),
            (new_id, new_receipt, new_back, 0, 0),
        ):
            with self.subTest(report_id=number):
                result = get_review(self.center, number)
                self.assertEqual((result.report_id, result.task_id, result.front_id, result.back_id),
                                 (number, task, front, back))
                self.assertEqual((result.front_crossings, result.back_crossings), (0, 0))
                self.assertEqual((result.seam.before, result.seam.after, result.seam.change, result.seam.crossings),
                                 (0, last, last, count))
                self.assertEqual(result.total_crossings, count)
                self.assertEqual(result.receipt, receipt)
                self.assertEqual((receipt.report_id, receipt.task_id), (number, task))
        self.assertEqual(get_accepted_piece(self.center, original_back).piece.revision_id, original_revision)
        self.assertEqual(get_accepted_piece(self.center, new_back).piece.revision_id, corrected)
        with self.assertRaises(KeyError):
            get_review(self.center, new_id + 100)

    def test_parent_ownership(self):
        task = self.new_task(back_origin=WEST)
        other = self.new_task(back_origin=WEST, name='Alternate protocol')
        first = record_segment(self.left, task, 1, [(0, 0), (1, 0)])
        wrong_slot = record_segment(self.left, task, 2, [(2, 0), (3, 1)])
        wrong_task = record_segment(self.left, other, 1, [(0, 1), (1, 1)])
        sources = [get_revision(self.left, number) for number in (first, wrong_slot, wrong_task)]
        for invalid, error_type in ((100000, KeyError), (wrong_slot, ValueError), (wrong_task, ValueError)):
            with self.subTest(parent=invalid):
                with self.assertRaises(error_type):
                    record_segment(self.left, task, 1, [(0, 0), (1, 1)], parent_id=invalid)
                self.assertEqual(self.revision_counts(), (3, 6))
        self.assertEqual([get_revision(self.left, source.revision_id) for source in sources], sources)
        valid = record_segment(self.left, task, 1, [(0, 0), (1, 1)], parent_id=first)
        self.assertEqual(get_revision(self.left, valid).parent_id, first)
        self.assertEqual(self.revision_counts(), (4, 8))

    def test_explicit_revision(self):
        task = self.new_task()
        original = record_segment(self.right, task, 2, [(2, 1), (3, 1)])
        corrected = record_segment(self.right, task, 2, [(2, 0), (3, 0)], parent_id=original)
        old_piece = get_piece(self.right, freeze_segment(self.right, original))
        new_piece = get_piece(self.right, freeze_segment(self.right, corrected))
        self.assertNotEqual(old_piece.piece_id, new_piece.piece_id)
        self.assertEqual((old_piece.revision_id, old_piece.first, old_piece.last), (original, 1, 1))
        self.assertEqual((new_piece.revision_id, new_piece.first, new_piece.last), (corrected, 0, 0))
        self.assertEqual(get_revision(self.right, corrected).parent_id, original)
        self.assertEqual(get_revision(self.right, original).samples, ((2, 1), (3, 1)))

    def test_reinitialize(self):
        task = self.new_task(name='User fixture', threshold='1/2', limit='3/2')
        original = record_segment(self.left, task, 1, [(0, 0), (1, 0)])
        corrected = record_segment(self.left, task, 1, [(0, '-1/3'), (1, 0)], parent_id=original)
        front_piece = freeze_segment(self.left, original)
        corrected_piece = freeze_segment(self.left, corrected)
        back_revision = record_segment(self.right, task, 2, [(2, 1), (3, 1)])
        back_piece = freeze_segment(self.right, back_revision)
        from_front = export_segment(self.left, front_piece)
        from_corrected = export_segment(self.left, corrected_piece)
        from_back = export_segment(self.right, back_piece)
        corrected_acceptance = self.send(self.left, corrected)
        from intake.registry import accept_segment
        front, back = (accept_segment(self.center, wire) for wire in (from_front, from_back))
        report, receipt = issue_review(self.center, task, front, back)
        task_before = get_task(self.center, task)
        revisions_before = [get_revision(self.left, rev) for rev in (original, corrected)]
        back_before = get_revision(self.right, back_revision)
        acceptances = (front, back, corrected_acceptance)
        accepted_before = [get_accepted_piece(self.center, number) for number in acceptances]
        result_before = get_review(self.center, report)
        self.assertEqual(result_before.total_crossings, 1)
        self.center.close()
        self.left.close()
        self.right.close()

        self.center = self.open_db('center')
        self.left = self.open_db(WEST)
        self.right = self.open_db(EAST)
        for _ in range(2):
            self.init_center(self.center)
            self.init_station(self.left, WEST)
            self.init_station(self.right, EAST)
        with self.assertRaises(ValueError):
            self.init_station(self.left, EAST)
        self.init_station(self.left, WEST)

        for db in (self.center, self.left, self.right):
            self.assertEqual(get_task(db, task), task_before)
            self.assertEqual(db.execute('SELECT count(*) FROM task_catalog').fetchone()[0], 1)
        self.assertEqual([get_revision(self.left, rev) for rev in (original, corrected)], revisions_before)
        self.assertEqual(get_revision(self.right, back_revision), back_before)
        self.assertEqual(self.revision_counts(), (2, 4))
        self.assertEqual(self.revision_counts(self.right), (1, 2))
        self.assertEqual(export_segment(self.left, front_piece), from_front)
        self.assertEqual(export_segment(self.left, corrected_piece), from_corrected)
        self.assertEqual(export_segment(self.right, back_piece), from_back)
        self.assertEqual([get_accepted_piece(self.center, number) for number in acceptances], accepted_before)
        self.assertEqual(self.intake_counts(), (3, 3))
        self.assertEqual(get_review(self.center, report), result_before)
        self.assertEqual(get_review(self.center, report).receipt, receipt)
        self.assertEqual(self.review_counts(), (1, 1))
