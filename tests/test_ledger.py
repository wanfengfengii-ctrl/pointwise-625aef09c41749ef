from dataclasses import replace
from fractions import Fraction

from ledger.ingest import record_segment
from ledger.query import get_revision
from plan.catalog import get_task, install_task_snapshot
from plan.tasks import open_task
from tests.fixtures import EAST, WEST, LabCase, task_layout


class TestLedger(LabCase):
    def test_missing_sample(self):
        task = self.new_task()
        counts = self.revision_counts()
        with self.assertRaises(ValueError):
            record_segment(self.left, task, 1, [(0, 0)])
        self.assertEqual(self.revision_counts(), counts)

    def test_readings_in_plan_order(self):
        task = self.new_task()
        number = record_segment(self.left, task, 1, iter([(1, '1/2'), (0, 0)]))
        revision = get_revision(self.left, number)
        self.assertEqual(revision.samples, ((0, Fraction(0)), (1, Fraction(1, 2))))
        self.assertTrue(all(type(value) is Fraction for _, value in revision.samples))
        self.assertEqual((revision.task_id, revision.slot, revision.origin, revision.rig, revision.parent_id),
                         (task, 1, WEST, 'front-rig', None))

    def test_task_validation(self):
        cases = (
            ((0, 1), (3, 4), 1),
            ((), (2, 3), 1),
            ((0, 2), (3, 4), 1),
            ((0, 1), (), 1),
            ((0, 1), (2, 3), -1),
            ((0, True), (2, 3), 1),
        )
        for front, back, limit in cases:
            with self.subTest(front=front, back=back, limit=limit):
                with self.assertRaises(ValueError):
                    open_task(self.center, 'Compression', 'kN', 1, limit, task_layout(front, back))
                self.assertEqual(self.center.execute('SELECT count(*) FROM task_catalog').fetchone()[0], 0)
        valid = self.new_task()
        self.assertEqual(get_task(self.center, valid).segments, task_layout())
        self.assertEqual(get_revision(self.left, record_segment(self.left, valid, 1, [(0, 0), (1, 1)])).samples,
                         ((0, Fraction(0)), (1, Fraction(1))))

    def test_snapshot_install(self):
        task = open_task(self.center, 'Bend', 'kN', '1/3', 1, task_layout())
        original = get_task(self.center, task)
        with self.assertRaises(KeyError):
            get_task(self.left, task)
        self.assertEqual(install_task_snapshot(self.left, original), task)
        self.assertEqual(install_task_snapshot(self.left, original), task)
        conflict = replace(original, protocol=replace(original.protocol, unit='N'))
        with self.assertRaises(ValueError):
            install_task_snapshot(self.left, conflict)
        self.assertEqual(get_task(self.left, task), original)
        self.assertEqual(self.left.execute('SELECT count(*) FROM task_catalog').fetchone()[0], 1)

    def test_exact_values(self):
        task = self.new_task(threshold='-1/3', limit='0.5')
        revision = record_segment(self.left, task, 1, [(0, '-1/3'), (1, '0.5')])
        self.assertEqual(get_revision(self.left, revision).samples, ((0, Fraction(-1, 3)), (1, Fraction(1, 2))))
        self.assertEqual(get_task(self.left, task).protocol.threshold, Fraction(-1, 3))
        self.assertEqual(get_task(self.left, task).protocol.max_change, Fraction(1, 2))
        for value in (None, '', '1/0', 0.5, True):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    record_segment(self.left, task, 1, [(0, value), (1, 0)])
                self.assertEqual(self.revision_counts(), (1, 2))

    def test_coverage_variants(self):
        task = self.new_task()
        for beats in ((0, 2), (0, 0), (0, 1, 2), ()):
            with self.subTest(beats=beats):
                with self.assertRaises(ValueError):
                    record_segment(self.left, task, 1, [(beat, 0) for beat in beats])
                self.assertEqual(self.revision_counts(), (0, 0))
        valid = record_segment(self.left, task, 1, [(0, '1/2'), (1, 1)])
        self.assertEqual(get_revision(self.left, valid).samples, ((0, Fraction(1, 2)), (1, Fraction(1))))
        self.assertEqual(self.revision_counts(), (1, 2))

    def test_station_ownership_and_unknown_task(self):
        task = self.new_task()
        with self.assertRaises(ValueError):
            record_segment(self.left, task, 2, [(2, 0), (3, 0)])
        with self.assertRaises(KeyError):
            record_segment(self.left, task + 100, 1, [(0, 0), (1, 0)])
        self.assertEqual(self.revision_counts(), (0, 0))
        revision = record_segment(self.right, task, 2, [(2, 0), (3, 0)])
        self.assertEqual(get_revision(self.right, revision).origin, EAST)
