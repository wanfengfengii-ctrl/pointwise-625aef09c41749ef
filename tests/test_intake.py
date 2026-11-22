import json

from intake.registry import accept_segment, get_accepted_piece
from ledger.ingest import record_segment
from station.export import export_segment
from station.freeze import freeze_segment
from tests.fixtures import EAST, WEST, LabCase


def changed_wire(wire, **updates):
    value = json.loads(wire)
    value.update(updates)
    return json.dumps(value).encode('utf-8')


class TestIntake(LabCase):
    def front_wire(self, task):
        revision = record_segment(self.left, task, 1, [(0, 0), (1, 0)])
        piece = freeze_segment(self.left, revision)
        return export_segment(self.left, piece)

    def test_replay_then_conflict(self):
        wire = self.front_wire(self.new_task())
        number = accept_segment(self.center, wire)
        first = get_accepted_piece(self.center, number)
        self.assertEqual(accept_segment(self.center, wire), number)
        rearranged = dict(reversed(list(json.loads(wire).items())))
        equivalent = json.dumps(rearranged, indent=2).encode('utf-8')
        self.assertNotEqual(wire, equivalent)
        self.assertEqual(accept_segment(self.center, equivalent), number)
        clash = changed_wire(wire, last='1/1', crossings=1)
        with self.assertRaises(ValueError):
            accept_segment(self.center, clash)
        self.assertEqual(self.intake_counts(), (1, 1))
        self.assertEqual(get_accepted_piece(self.center, number), first)
        self.assertEqual(first.payload, wire)
        self.assertEqual((first.receipt.acceptance_id, first.receipt.origin, first.receipt.piece_id),
                         (number, WEST, first.piece.piece_id))

    def test_stable_export(self):
        task = self.new_task()
        revision = record_segment(self.left, task, 1, [(0, '-1/3'), (1, '1/2')])
        piece = freeze_segment(self.left, revision)
        wire = export_segment(self.left, piece)
        expected = (
            f'{{"version":1,"origin":"west","piece_id":{piece},"task_id":{task},'
            f'"slot":1,"revision_id":{revision},"first":"-1/3","last":"1/2","crossings":0}}'
        ).encode('utf-8')
        self.assertEqual(wire, expected)
        self.assertEqual(export_segment(self.left, piece), wire)
        self.left.close()
        station = self.open_db(WEST)
        self.assertEqual(export_segment(station, piece), wire)
        station.close()
        accepted = get_accepted_piece(self.center, accept_segment(self.center, wire))
        self.assertEqual(accepted.payload, wire)
        self.assertEqual(accepted.piece.revision_id, revision)

    def test_invalid_piece(self):
        task = self.new_task()
        wire = self.front_wire(task)
        missing = json.loads(wire)
        del missing['last']
        invalid = (
            b'{', b'\xff', changed_wire(wire, version=2), changed_wire(wire, version=True),
            json.dumps(missing).encode('utf-8'), changed_wire(wire, extra='field'),
            changed_wire(wire, first='1/0'), changed_wire(wire, last='2/2'),
            changed_wire(wire, last=1), changed_wire(wire, task_id=task + 100),
            changed_wire(wire, slot=True), changed_wire(wire, crossings=2),
            changed_wire(wire, crossings=-1), changed_wire(wire, piece_id=True),
            b'{"version":1,' + wire[1:],
        )
        for payload in invalid:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    accept_segment(self.center, payload)
                self.assertEqual(self.intake_counts(), (0, 0))
        valid = accept_segment(self.center, wire)
        self.assertEqual(get_accepted_piece(self.center, valid).payload, wire)

    def test_wrong_source(self):
        wire = self.front_wire(self.new_task())
        with self.assertRaises(ValueError):
            accept_segment(self.center, changed_wire(wire, origin=EAST))
        self.assertEqual(self.intake_counts(), (0, 0))

    def test_single_beat_summary(self):
        task = self.new_task((0,), (1,))
        rev = record_segment(self.left, task, 1, [(0, 0)])
        wire = export_segment(self.left, freeze_segment(self.left, rev))
        for payload in (changed_wire(wire, last='1/1'), changed_wire(wire, crossings=1)):
            with self.assertRaises(ValueError):
                accept_segment(self.center, payload)
        self.assertEqual(self.intake_counts(), (0, 0))
        self.assertEqual(get_accepted_piece(self.center, accept_segment(self.center, wire)).piece.crossings, 0)

    def test_origin_namespace(self):
        task = self.new_task()
        front = self.front_wire(task)
        revision = record_segment(self.right, task, 2, [(2, 1), (3, 1)])
        back = export_segment(self.right, freeze_segment(self.right, revision))
        self.assertEqual(json.loads(front)['piece_id'], json.loads(back)['piece_id'])
        first = accept_segment(self.center, front)
        second = accept_segment(self.center, back)
        self.assertNotEqual(first, second)
        self.assertEqual(accept_segment(self.center, front), first)
        self.assertEqual(accept_segment(self.center, back), second)
        self.assertEqual(get_accepted_piece(self.center, first).receipt.origin, WEST)
        self.assertEqual(get_accepted_piece(self.center, second).receipt.origin, EAST)
        self.assertEqual(self.intake_counts(), (2, 2))
