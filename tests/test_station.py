from fractions import Fraction

from intake.decode import decode_v1
from ledger.ingest import record_segment
from ledger.query import get_revision
from station.export import export_segment
from station.freeze import freeze_segment
from station.storage import get_piece
from tests.fixtures import LabCase


class TestStation(LabCase):
    def test_local_jump_exceeds_limit(self):
        task = self.new_task()
        revision = record_segment(self.left, task, 1, [(0, 0), (1, 2)])
        with self.assertRaises(ValueError):
            freeze_segment(self.left, revision)
        self.assertEqual(get_revision(self.left, revision).samples, ((0, 0), (1, 2)))
        self.assertEqual(self.left.execute('SELECT count(*) FROM station_pieces').fetchone()[0], 0)

    def test_inclusive_limits(self):
        cases = ((Fraction(1, 2), 0, Fraction(1, 2), 1), (Fraction(0), 1, 1, 0))
        for limit, first, last, expected in cases:
            with self.subTest(limit=limit):
                task = self.new_task(threshold='1/2', limit=limit)
                revision = record_segment(self.left, task, 1, [(0, first), (1, last)])
                piece = get_piece(self.left, freeze_segment(self.left, revision))
                self.assertEqual((piece.first, piece.last, piece.crossings), (first, last, expected))

    def test_descending_jump(self):
        task = self.new_task()
        original = record_segment(self.left, task, 1, [(0, 2), (1, 0)])
        with self.assertRaises(ValueError):
            freeze_segment(self.left, original)
        self.assertEqual(get_revision(self.left, original).samples, ((0, 2), (1, 0)))
        self.assertEqual(self.left.execute('SELECT count(*) FROM station_pieces').fetchone()[0], 0)
        valid = record_segment(self.left, task, 1, [(0, 2), (1, 1)], parent_id=original)
        piece = get_piece(self.left, freeze_segment(self.left, valid))
        self.assertEqual((piece.first, piece.last, piece.crossings), (2, 1, 0))

    def test_segment_counts(self):
        task = self.new_task(tuple(range(6)), (6,))
        values = (1, 1, 0, 1, 0, 1)
        front_revision = record_segment(self.left, task, 1, enumerate(values))
        back_revision = record_segment(self.right, task, 2, [(6, 1)])
        front = decode_v1(export_segment(self.left, freeze_segment(self.left, front_revision)))
        back = decode_v1(export_segment(self.right, freeze_segment(self.right, back_revision)))
        self.assertEqual((front.first, front.last, front.crossings), (1, 1, 2))
        self.assertEqual((back.first, back.last, back.crossings), (1, 1, 0))
        with self.assertRaises(KeyError):
            freeze_segment(self.left, front_revision + 100)
        with self.assertRaises(KeyError):
            export_segment(self.left, front.piece_id + 100)
