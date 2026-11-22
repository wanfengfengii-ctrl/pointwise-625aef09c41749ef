import json
import sqlite3

from intake.registry import (
    accept_committed_segment, accept_segment, get_accepted_piece, get_committed_piece,
)
from ledger.ingest import record_segment
from review.history import get_amendment, get_review
from review.issue import issue_amendment, issue_review
from station.export import (
    export_change_proof, export_committed_segment, export_segment,
)
from station.freeze import freeze_segment
from tests.fixtures import EAST, FailBeforeCommit, LabCase
from tests.test_intake import changed_wire


class AmendmentCase(LabCase):
    """Helpers to build report pairs plus their station-side evidence."""

    def prepare(self, task, slots):
        """Freeze revisions and return per-slot evidence documents.

        ``slots`` holds two ``(old_values, new_values)`` pairs; ``None`` for
        ``new_values`` means the original revision is reused unchanged.
        """
        pieces = []
        for slot, (old_values, new_values) in enumerate(slots, start=1):
            db = self.left if slot == 1 else self.right
            beats = self.plan_beats(task, slot)
            original = record_segment(
                db, task, slot, list(zip(beats, old_values, strict=True)),
            )
            old_piece = freeze_segment(db, original)
            pair = {'old_revision': original, 'old_piece': old_piece}
            if new_values is not None:
                corrected = record_segment(
                    db, task, slot,
                    list(zip(self.plan_beats(task, slot), new_values, strict=True)),
                    parent_id=original,
                )
                pair['new_revision'] = corrected
                pair['new_piece'] = freeze_segment(db, corrected)
                pair['proof'] = export_change_proof(db, old_piece, pair['new_piece'])
            else:
                pair['new_revision'] = original
                pair['new_piece'] = old_piece
            pair['old_wire'], pair['old_commitment'] = export_committed_segment(db, old_piece)
            if new_values is not None:
                pair['new_wire'], pair['new_commitment'] = export_committed_segment(
                    db, pair['new_piece'])
            else:
                pair['new_wire'], pair['new_commitment'] = (
                    pair['old_wire'], pair['old_commitment'])
            pieces.append(pair)
        return pieces

    def plan_beats(self, task, slot):
        from plan.catalog import get_task
        return get_task(self.center, task).segments[slot - 1].beats

    def accept(self, piece):
        return accept_committed_segment(self.center, piece['old_wire'], piece['old_commitment'])

    def run_reports(self, task, pieces):
        old_ids = [self.accept(p) for p in pieces]
        new_ids = [
            accept_committed_segment(self.center, p['new_wire'], p['new_commitment'])
            for p in pieces
        ]
        old_report, _ = issue_review(self.center, task, *old_ids)
        new_report, _ = issue_review(self.center, task, *new_ids)
        proofs = {slot: p['proof'] for slot, p in enumerate(pieces, start=1) if 'proof' in p}
        return old_report, new_report, old_ids, new_ids, proofs

    def run_amend(self, task, pieces):
        old_report, new_report, old_ids, new_ids, proofs = self.run_reports(task, pieces)
        amendment_id, receipt = issue_amendment(
            self.center, old_report, new_report, proofs)
        return amendment_id, receipt, old_report, new_report, old_ids, new_ids

    def amendment_counts(self, db=None):
        db = self.center if db is None else db
        return tuple(
            db.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
            for table in ('amendment_reports', 'amendment_proofs', 'amendment_receipts')
        )


class TestAmendment(AmendmentCase):
    def test_moved_crossing_same_total(self):
        task = self.new_task(tuple(range(6)), (6,))
        pieces = self.prepare(task, [((0, 1, 0, 0, 0, 0), (0, 0, 1, 0, 0, 0)), ((0,), None)])
        amendment_id, receipt, old_report, new_report, old_ids, new_ids = self.run_amend(task, pieces)
        old = get_review(self.center, old_report)
        new = get_review(self.center, new_report)
        self.assertEqual(old.total_crossings, new.total_crossings)
        self.assertEqual(old.total_crossings, 1)
        result = get_amendment(self.center, amendment_id)
        self.assertEqual(result['amendment_id'], amendment_id)
        self.assertEqual(result['task_id'], task)
        self.assertEqual(result['reports'], (old_report, new_report))
        self.assertEqual(result['acceptances'], ((old_ids[0], old_ids[1]), (new_ids[0], new_ids[1])))
        self.assertEqual(result['added'], ((1, 2),))
        self.assertEqual(result['removed'], ((0, 1),))
        self.assertEqual(result['receipt'], receipt)
        self.assertEqual(receipt, (amendment_id, task))
        digests = result['proof_digests']
        self.assertEqual([slot for slot, _ in digests], [1])
        self.assertEqual(digests[0][1], __import__('hashlib').sha256(pieces[0]['proof']).hexdigest())

    def test_direct_correction_without_change(self):
        task = self.new_task(tuple(range(6)), (6,))
        pieces = self.prepare(task, [((0, 1, 0, 0, 0, 0), (0, 1, 0, 0, 0, 0)), ((0,), None)])
        amendment_id, receipt, old_report, new_report, _, _ = self.run_amend(task, pieces)
        self.assertEqual(get_review(self.center, old_report).total_crossings,
                         get_review(self.center, new_report).total_crossings)
        result = get_amendment(self.center, amendment_id)
        self.assertEqual(result['added'], ())
        self.assertEqual(result['removed'], ())
        self.assertEqual([slot for slot, _ in result['proof_digests']], [1])

    def test_both_sides_of_seam(self):
        task = self.new_task((0, 1), (2, 3))
        pieces = self.prepare(task, [((0, 0), (0, 1)), ((1, 1), (0, 1))])
        amendment_id, _, old_report, new_report, _, _ = self.run_amend(task, pieces)
        added_totals = [get_review(self.center, r).total_crossings for r in (old_report, new_report)]
        self.assertEqual(added_totals, [1, 2])
        result = get_amendment(self.center, amendment_id)
        self.assertEqual(result['added'], ((0, 1), (2, 3)))
        self.assertEqual(result['removed'], ((1, 2),))
        self.assertEqual([slot for slot, _ in result['proof_digests']], [1, 2])

    def test_unchanged_reuse_needs_no_proof(self):
        task = self.new_task((0, 1), (2, 3))
        pieces = self.prepare(task, [((0, 0), None), ((0, 0), None)])
        # Both slots identical: no statements changed and no proofs submitted.
        amendment_id, _, _, _, _, _ = self.run_amend(task, pieces)
        result = get_amendment(self.center, amendment_id)
        self.assertEqual((result['added'], result['removed'], result['proof_digests']), ((), (), ()))


class TestAmendmentRejection(AmendmentCase):
    def test_missing_or_extra_proof(self):
        task = self.new_task((0, 1), (2, 3))
        pieces = self.prepare(task, [((0, 1), (0, 0)), ((0, 0), None)])
        old_report, new_report, _, _, _ = self.run_reports(task, pieces)
        with self.assertRaises(ValueError):
            issue_amendment(self.center, old_report, new_report, {})
        with self.assertRaises(ValueError):
            issue_amendment(self.center, old_report, new_report,
                            {1: pieces[0]['proof'], 2: pieces[0]['proof']})
        self.assertEqual(self.amendment_counts(), (0, 0, 0))

    def test_unknown_and_crossed_identities(self):
        task = self.new_task((0, 1), (2, 3))
        pieces = self.prepare(task, [((0, 1), (0, 0)), ((0, 0), None)])
        old_report, new_report, _, _, _ = self.run_reports(task, pieces)
        with self.assertRaises(KeyError):
            issue_amendment(self.center, old_report + 100, new_report, {1: pieces[0]['proof']})
        with self.assertRaises(KeyError):
            issue_amendment(self.center, old_report, new_report + 100, {1: pieces[0]['proof']})
        with self.assertRaises(ValueError):
            issue_amendment(self.center, old_report, old_report, {})

    def test_mismatched_reports_tasks(self):
        task = self.new_task((0, 1), (2, 3))
        other = self.new_task((0, 1), (2, 3), name='Alternate')
        pieces = self.prepare(task, [((0, 1), (0, 0)), ((0, 0), None)])
        old_report, new_report, _, _, _ = self.run_reports(task, pieces)
        other_front = self.send(self.left, record_segment(self.left, other, 1, [(0, 0), (1, 0)]))
        other_back = self.send(self.right, record_segment(self.right, other, 2, [(2, 0), (3, 0)]))
        foreign, _ = issue_review(self.center, other, other_front, other_back)
        with self.assertRaises(ValueError):
            issue_amendment(self.center, old_report, foreign, {1: pieces[0]['proof']})

    def test_tampered_values_rejected(self):
        task = self.new_task((0, 1, 2, 3), (4, 5))
        pieces = self.prepare(task, [((0, 0, 0, 0), (0, 1, 0, 0)), ((0, 0), None)])
        old_report, new_report, _, _, _ = self.run_reports(task, pieces)
        document = json.loads(pieces[0]['proof'])
        self.assertTrue(document['values'])
        document['values'][0][1] = '5/1'
        with self.assertRaises(ValueError):
            issue_amendment(self.center, old_report, new_report,
                            {1: json.dumps(document).encode('utf-8')})
        self.assertEqual(self.amendment_counts(), (0, 0, 0))

    def test_wrong_piece_binding(self):
        task = self.new_task((0, 1, 2, 3), (4, 5))
        pieces = self.prepare(task, [((0, 0, 0, 0), (0, 1, 0, 0)), ((0, 0), None)])
        old_report, new_report, _, _, _ = self.run_reports(task, pieces)
        document = json.loads(pieces[0]['proof'])
        document['old']['piece_id'] += 100
        with self.assertRaises(ValueError):
            issue_amendment(self.center, old_report, new_report,
                            {1: json.dumps(document).encode('utf-8')})

    def test_surplus_and_missing_openings_rejected(self):
        task = self.new_task(tuple(range(6)), (6,))
        pieces = self.prepare(task, [((0, 1, 0, 0, 0, 0), (0, 0, 1, 0, 0, 0)), ((0,), None)])
        old_report, new_report, _, _, _ = self.run_reports(task, pieces)
        document = json.loads(pieces[0]['proof'])
        surplus = dict(document)
        surplus['values'] = document['values'] + [[4, '0/1', '0/1']]
        with self.assertRaises(ValueError):
            issue_amendment(self.center, old_report, new_report,
                            {1: json.dumps(surplus).encode('utf-8')})
        missing = dict(document)
        missing['values'] = document['values'][:-1]
        with self.assertRaises(ValueError):
            issue_amendment(self.center, old_report, new_report,
                            {1: json.dumps(missing).encode('utf-8')})
        self.assertEqual(self.amendment_counts(), (0, 0, 0))

    def test_non_direct_parent_rejected(self):
        task = self.new_task((0, 1, 2, 3), (4, 5))
        pieces = self.prepare(task, [((0, 0, 0, 0), (0, 1, 0, 0)), ((0, 0), None)])
        # Build a second correction directly on the original revision again.
        second = record_segment(self.left, task, 1, [(0, 0), (1, 0), (2, 0), (3, 0)],
                                parent_id=pieces[0]['old_revision'])
        second_piece = freeze_segment(self.left, second)
        _, commitment = export_committed_segment(self.left, second_piece)
        wire, _ = export_committed_segment(self.left, second_piece)
        extra = accept_committed_segment(self.center, wire, commitment)
        old_report, _, old_ids, _, _ = self.run_reports(task, pieces)
        # The sibling correction is not a direct child of the old piece.
        sibling_report, _ = issue_review(self.center, task, extra, old_ids[1])
        with self.assertRaises(ValueError):
            issue_amendment(self.center, old_report, sibling_report, {1: pieces[0]['proof']})
        self.assertEqual(self.amendment_counts(), (0, 0, 0))

    def test_uncommitted_swap_rejected(self):
        task = self.new_task((0, 1), (2, 3))
        pieces = self.prepare(task, [((0, 1), (0, 0)), ((0, 0), None)])
        old_report, _, old_ids, _, _ = self.run_reports(task, pieces)
        # Plain-V1 acceptance of the corrected front has no commitment to check.
        revision = record_segment(self.left, task, 1, [(0, 0), (1, 0)],
                                  parent_id=pieces[0]['old_revision'])
        piece = freeze_segment(self.left, revision)
        plain = accept_segment(self.center, export_segment(self.left, piece))
        plain_report, _ = issue_review(self.center, task, plain, old_ids[1])
        with self.assertRaises(ValueError):
            issue_amendment(self.center, old_report, plain_report,
                            {1: pieces[0]['proof']})
        self.assertEqual(self.amendment_counts(), (0, 0, 0))

    def test_proof_private_to_another_slot(self):
        task = self.new_task((0, 1), (2, 3))
        pieces = self.prepare(task, [((0, 1), (0, 0)), ((0, 0), (1, 1))])
        old_report, new_report, _, _, _ = self.run_reports(task, pieces)
        with self.assertRaises(ValueError):
            issue_amendment(self.center, old_report, new_report, {1: pieces[1]['proof']})
        self.assertEqual(self.amendment_counts(), (0, 0, 0))

    def test_plain_v1_cannot_gain_commitment(self):
        task = self.new_task((0, 1), (2, 3))
        revision = record_segment(self.left, task, 1, [(0, 0), (1, 1)])
        piece = freeze_segment(self.left, revision)
        wire = export_segment(self.left, piece)
        acceptance = accept_segment(self.center, wire)
        _, commitment = export_committed_segment(self.left, piece)
        with self.assertRaises(ValueError):
            accept_committed_segment(self.center, wire, commitment)
        self.assertEqual(self.intake_counts(), (1, 1))
        self.assertIsNone(get_accepted_piece(self.center, acceptance).commitment)
        with self.assertRaises(ValueError):
            get_committed_piece(self.center, acceptance)

    def test_commitment_replay_and_conflict(self):
        task = self.new_task((0, 1), (2, 3))
        revision = record_segment(self.left, task, 1, [(0, 0), (1, 1)])
        piece = freeze_segment(self.left, revision)
        wire, commitment = export_committed_segment(self.left, piece)
        first = accept_committed_segment(self.center, wire, commitment)
        # A plain V1 replay of the same piece keeps the committed number.
        self.assertEqual(accept_segment(self.center, wire), first)
        self.assertEqual(accept_segment(self.center, export_segment(self.left, piece)), first)
        rearranged_wire = json.dumps(
            dict(reversed(list(json.loads(wire).items()))), indent=2).encode('utf-8')
        rearranged_commitment = json.dumps(
            dict(reversed(list(json.loads(commitment).items())))).encode('utf-8')
        self.assertNotEqual(rearranged_commitment, commitment)
        self.assertEqual(
            accept_committed_segment(self.center, rearranged_wire, rearranged_commitment), first)
        stored = get_committed_piece(self.center, first).commitment_payload
        self.assertEqual(json.loads(stored), json.loads(commitment))
        with self.assertRaises(ValueError):
            accept_committed_segment(self.center, changed_wire(wire, last='9/1'), commitment)
        other = dict(json.loads(commitment))
        other['parent_revision_id'] = 5
        with self.assertRaises(ValueError):
            accept_committed_segment(self.center, wire, json.dumps(other).encode('utf-8'))
        self.assertEqual(self.intake_counts(), (1, 1))

    def test_bad_commitment_structure(self):
        task = self.new_task((0, 1), (2, 3))
        revision = record_segment(self.left, task, 1, [(0, 0), (1, 1)])
        piece = freeze_segment(self.left, revision)
        wire, commitment = export_committed_segment(self.left, piece)
        document = json.loads(commitment)
        variants = (
            b'{}', changed_wire(commitment, version=2), changed_wire(commitment, extra=1),
            changed_wire(commitment, origin=EAST), changed_wire(commitment, task_id=task + 7),
            changed_wire(commitment, slot=2), changed_wire(commitment, piece_id=piece + 3),
            changed_wire(commitment, revision_id=revision + 3),
            changed_wire(commitment, beats=[]),
        )
        shortened = dict(document)
        shortened['beats'] = document['beats'][:-1]
        variants = variants + (json.dumps(shortened).encode('utf-8'),)
        for payload in variants:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    accept_committed_segment(self.center, wire, payload)
                self.assertEqual(self.intake_counts(), (0, 0))

    def test_export_errors(self):
        task = self.new_task((0, 1), (2, 3))
        revision = record_segment(self.left, task, 1, [(0, 0), (1, 1)])
        piece = freeze_segment(self.left, revision)
        with self.assertRaises(KeyError):
            export_committed_segment(self.left, piece + 100)
        with self.assertRaises(KeyError):
            export_change_proof(self.left, piece, piece + 100)
        with self.assertRaises(ValueError):
            export_change_proof(self.left, piece, piece)
        other_revision = record_segment(self.left, task, 1, [(0, 0), (1, 1)])
        other_piece = freeze_segment(self.left, other_revision)
        with self.assertRaises(ValueError):
            export_change_proof(self.left, piece, other_piece)


class TestAmendmentCommit(AmendmentCase):
    def test_failure_leaves_nothing_and_retries(self):
        task = self.new_task((0, 1), (2, 3))
        pieces = self.prepare(task, [((0, 1), (0, 0)), ((0, 0), None)])
        old_report, new_report, _, _, _ = self.run_reports(task, pieces)
        self.assertEqual(self.amendment_counts(), (0, 0, 0))
        observer = self.open_db('center')

        def observe_pending():
            self.assertTrue(self.center.in_transaction)
            self.assertEqual(self.amendment_counts(), (1, 1, 1))
            self.assertEqual(self.amendment_counts(observer), (0, 0, 0))

        fail_once = FailBeforeCommit(observe_pending)
        with self.assertRaises(sqlite3.OperationalError) as caught:
            issue_amendment(self.center, old_report, new_report,
                            {1: pieces[0]['proof']}, before_commit=fail_once)
        self.assertIs(caught.exception, fail_once.error)
        self.assertFalse(self.center.in_transaction)
        self.assertEqual(self.amendment_counts(), (0, 0, 0))
        observer.close()

        amendment_id, receipt = issue_amendment(
            self.center, old_report, new_report, {1: pieces[0]['proof']},
            before_commit=fail_once)
        self.assertEqual(fail_once.calls, 2)
        result = get_amendment(self.center, amendment_id)
        self.assertEqual((result['added'], result['removed']), ((), ((0, 1),)))
        self.assertEqual(result['receipt'], receipt)

    def test_reopen_keeps_signed_amendment(self):
        task = self.new_task((0, 1), (2, 3))
        pieces = self.prepare(task, [((0, 1), (0, 0)), ((0, 0), None)])
        amendment_id, receipt, old_report, new_report, _, _ = self.run_amend(task, pieces)
        before = get_amendment(self.center, amendment_id)
        self.center.close()
        self.center = self.open_db('center')
        self.init_center(self.center)
        self.assertEqual(get_amendment(self.center, amendment_id), before)
        self.assertEqual(get_amendment(self.center, amendment_id)['receipt'], receipt)
        with self.assertRaises(KeyError):
            get_amendment(self.center, amendment_id + 100)

