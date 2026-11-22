from fractions import Fraction
import sqlite3

from intake.registry import get_accepted_piece
from ledger.ingest import record_segment
from review.history import get_review
from review.issue import issue_review
from tests.fixtures import FailBeforeCommit, LabCase


class TestReview(LabCase):
    def test_offline_seam_hits_threshold(self):
        task = self.new_task()
        front, back = self.offline_pieces(task, [(0, 0), (1, 0)], [(2, 1), (3, 1)])
        report_id, receipt = issue_review(self.center, task, front, back)
        result = get_review(self.center, report_id)
        self.assertEqual((result.task_id, result.front_id, result.back_id), (task, front, back))
        self.assertEqual((result.front_crossings, result.back_crossings, result.total_crossings), (0, 0, 1))
        self.assertEqual((result.seam.before, result.seam.after, result.seam.change, result.seam.crossings), (0, 1, 1, 1))
        self.assertEqual((receipt.report_id, receipt.task_id), (report_id, task))
        self.assertEqual(result.receipt, receipt)
        self.assertEqual(self.review_counts(), (1, 1))

    def test_seam_jump_exceeds_limit(self):
        task = self.new_task((0,), (1,))
        front_id, back_id = self.offline_pieces(task, [(0, 0)], [(1, 2)])
        before = tuple(get_accepted_piece(self.center, number) for number in (front_id, back_id))
        with self.assertRaises(ValueError):
            issue_review(self.center, task, front_id, back_id)
        self.assertEqual(self.review_counts(), (0, 0))
        self.assertEqual(self.intake_counts(), (2, 2))
        self.assertEqual(tuple(get_accepted_piece(self.center, number) for number in (front_id, back_id)), before)

    def test_ordered_selection(self):
        task = self.new_task()
        other_task = self.new_task(name='Bend')
        other_back = self.send(self.right, record_segment(self.right, other_task, 2, [(2, 1), (3, 1)]))
        front, back = self.offline_pieces(task, [(0, 0), (1, 0)], [(2, 1), (3, 1)])
        report_id, _ = issue_review(self.center, task, front, back)
        original = get_review(self.center, report_id)
        self.assertEqual(original.total_crossings, 1)
        for first, second in ((back, front), (front, front), (front, other_back)):
            with self.subTest(first=first, second=second):
                with self.assertRaises(ValueError):
                    issue_review(self.center, task, first, second)
                self.assertEqual(self.review_counts(), (1, 1))
        with self.assertRaises(KeyError):
            issue_review(self.center, task, front, back + 100)
        with self.assertRaises(KeyError):
            issue_review(self.center, task + 100, front, back)
        self.assertEqual(get_review(self.center, report_id), original)
        self.assertEqual(self.review_counts(), (1, 1))

    def test_actual_endpoints(self):
        task = self.new_task()
        selected = self.offline_pieces(task, [(0, 1), (1, 0)], [(2, 1), (3, 0)])
        report_id, _ = issue_review(self.center, task, *selected)
        result = get_review(self.center, report_id)
        self.assertEqual((result.seam.before, result.seam.after, result.seam.crossings, result.total_crossings), (0, 1, 1, 1))

    def test_full_sum(self):
        task = self.new_task((0, 1, 2), (3, 4, 5))
        selected = self.offline_pieces(task, [(0, 0), (1, 1), (2, 0)], [(3, 1), (4, 0), (5, 1)])
        report_id, _ = issue_review(self.center, task, *selected)
        result = get_review(self.center, report_id)
        self.assertEqual((result.front_crossings, result.seam.crossings, result.back_crossings, result.total_crossings),
                         (1, 1, 1, 3))

    def test_seam_limit_uses_actual_endpoints(self):
        task = self.new_task()
        selected = self.offline_pieces(task, [(0, 1), (1, 0)], [(2, 2), (3, 1)])
        self.assertEqual(self.intake_counts(), (2, 2))
        with self.assertRaises(ValueError):
            issue_review(self.center, task, *selected)
        self.assertEqual(self.intake_counts(), (2, 2))
        self.assertEqual(self.review_counts(), (0, 0))

    def test_fractional_and_descending_seams(self):
        task = self.new_task((0,), (1,), threshold='1/3', limit='1/2')
        up_front = self.send(self.left, record_segment(self.left, task, 1, [(0, '-1/6')]))
        up_back = self.send(self.right, record_segment(self.right, task, 2, [(1, '1/3')]))
        down_front = self.send(self.left, record_segment(self.left, task, 1, [(0, '1/3')]))
        down_back = self.send(self.right, record_segment(self.right, task, 2, [(1, '-1/6')]))
        self.left.close()
        self.right.close()
        for front, back, expected in ((up_front, up_back, 1), (down_front, down_back, 0)):
            report_id, _ = issue_review(self.center, task, front, back)
            result = get_review(self.center, report_id)
            self.assertEqual(result.seam.change, Fraction(1, 2))
            self.assertEqual((result.seam.crossings, result.total_crossings), (expected, expected))

    def test_commit_failure_can_retry(self):
        task = self.new_task()
        chosen = self.offline_pieces(task, [(0, 0), (1, 0)], [(2, 1), (3, 1)])
        before_pieces = tuple(get_accepted_piece(self.center, number) for number in chosen)
        before_counts = self.review_counts()
        self.assertEqual(before_counts, (0, 0))
        observer = self.open_db('center')

        def observe_pending_writes():
            self.assertTrue(self.center.in_transaction)
            self.assertEqual(self.review_counts(), (1, 1))
            self.assertEqual(self.review_counts(observer), before_counts)

        fail_once = FailBeforeCommit(observe_pending_writes)
        with self.assertRaises(sqlite3.OperationalError) as caught:
            issue_review(self.center, task, *chosen, before_commit=fail_once)
        self.assertIs(caught.exception, fail_once.error)
        self.assertEqual(fail_once.calls, 1)
        self.assertFalse(self.center.in_transaction)
        self.assertEqual(self.review_counts(), before_counts)
        observer.close()
        self.center.close()
        self.center = self.open_db('center')
        self.assertEqual(self.review_counts(), before_counts)
        self.assertEqual(tuple(get_accepted_piece(self.center, number) for number in chosen), before_pieces)
        report_id, receipt = issue_review(self.center, task, *chosen, before_commit=fail_once)
        self.assertEqual(fail_once.calls, 2)
        result = get_review(self.center, report_id)
        self.assertEqual((result.front_id, result.back_id), chosen)
        self.assertEqual(result.total_crossings, 1)
        self.assertEqual(result.receipt, receipt)
        self.assertEqual(self.review_counts(), (1, 1))
