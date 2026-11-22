from contextlib import closing
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from database import connect
from intake.registry import (
    accept_committed_segment, accept_segment, get_accepted_piece, initialize_intake,
)
from ledger.ingest import record_segment
from ledger.query import get_revision
from ledger.storage import initialize_ledger
from plan.catalog import get_task, initialize_catalog, install_task_snapshot
from plan.layout import SegmentLayout
from plan.rationals import rational_text
from plan.tasks import open_task
from review.history import get_amendment, get_review
from review.issue import issue_amendment, issue_review
from review.storage import initialize_review
from station.export import export_change_proof, export_committed_segment, export_segment
from station.freeze import freeze_segment
from station.storage import initialize_station


SAMPLE = Path(__file__).resolve().parent / 'examples' / 'day_shift.json'


def checked(actual, expected):
    if actual != expected:
        raise AssertionError(f'expected {expected!r}, got {actual!r}')


def receive_station(root, snapshot, slot, part, *, parent_id=None):
    with closing(connect(root / f'station-{slot}.sqlite')) as db:
        initialize_catalog(db)
        initialize_ledger(db, part['origin'])
        initialize_station(db)
        install_task_snapshot(db, snapshot)
        values = part['values'] if parent_id is None else part['corrected_values']
        samples = zip(part['beats'], values, strict=True)
        revision = record_segment(db, snapshot.task_id, slot, samples, parent_id=parent_id)
        if parent_id is not None:
            checked(get_revision(db, revision).parent_id, parent_id)
            checked([str(value) for _, value in get_revision(db, parent_id).samples],
                    [str(value) for value in part['values']])
        return revision, export_segment(db, freeze_segment(db, revision))


def counts(result):
    seam = result.seam
    return {
        'front_crossings': result.front_crossings,
        'back_crossings': result.back_crossings,
        'seam_values': [rational_text(seam.before), rational_text(seam.after)],
        'seam_change': rational_text(seam.change),
        'seam_crossings': seam.crossings,
        'total_crossings': result.total_crossings,
    }


def provenance(center, result):
    parents = [get_accepted_piece(center, number) for number in (result.front_id, result.back_id)]
    return {
        'report_id': result.report_id,
        'task_id': result.task_id,
        'acceptances': [parent.acceptance_id for parent in parents],
        'revisions': [parent.piece.revision_id for parent in parents],
        'receipt': [result.receipt.report_id, result.receipt.task_id],
    }


def emit(case_id, inputs, expected, actual, downstream_expected, downstream_actual, paths, oracle):
    checked(actual, expected)
    checked(downstream_actual, downstream_expected)
    event = {
        'case_id': case_id, 'input': inputs, 'expected': expected, 'actual': actual,
        'downstream_expected': downstream_expected, 'downstream_actual': downstream_actual,
        'code_paths': paths, 'oracle': oracle,
    }
    print('POINTWISE_SCENARIO ' + json.dumps(event, ensure_ascii=False, separators=(',', ':')))


def run(root, data):
    front, back = data['front'], data['back']
    segments = tuple(
        SegmentLayout(slot, part['origin'], part['rig'], tuple(part['beats']))
        for slot, part in enumerate((front, back), start=1)
    )
    old_expected = {
        'front_crossings': 0, 'back_crossings': 0, 'seam_values': ['0/1', '1/1'],
        'seam_change': '1/1', 'seam_crossings': 1, 'total_crossings': 1,
    }
    new_expected = {
        'front_crossings': 0, 'back_crossings': 0, 'seam_values': ['0/1', '0/1'],
        'seam_change': '0/1', 'seam_crossings': 0, 'total_crossings': 0,
    }
    center_path = root / 'center.sqlite'
    with closing(connect(center_path)) as center:
        initialize_catalog(center)
        initialize_intake(center)
        initialize_review(center)
        task_id = open_task(center, data['protocol'], data['unit'], data['threshold'], data['max_change'], segments)
        snapshot = get_task(center, task_id)
        first_revision, first_wire = receive_station(root, snapshot, 1, front)
        original_revision, original_wire = receive_station(root, snapshot, 2, back)
        front_id = accept_segment(center, first_wire)
        original_id = accept_segment(center, original_wire)
        report, receipt = issue_review(center, task_id, front_id, original_id)
        checked((receipt.report_id, receipt.task_id), (report, task_id))
        original = get_review(center, report)
        first_provenance = {
            'report_id': report, 'task_id': task_id, 'acceptances': [front_id, original_id],
            'revisions': [first_revision, original_revision], 'receipt': [report, task_id],
        }
        emit(
            'seam_count',
            {'threshold': data['threshold'], 'max_change': data['max_change'],
             'front': front['values'], 'back': back['values'], 'stations_closed': True},
            old_expected, counts(original), first_provenance, provenance(center, original),
            ['station/freeze.py', 'intake/registry.py', 'review/join.py', 'review/history.py'],
            '手算相邻对 0→0、0→1、1→1，只有接缝达到门槛。原选件以接纳返回的编号核对。',
        )

        corrected_revision, corrected_wire = receive_station(root, snapshot, 2, back, parent_id=original_revision)
        corrected_id = accept_segment(center, corrected_wire)
        new_report, new_receipt = issue_review(center, task_id, front_id, corrected_id)
        checked((new_receipt.report_id, new_receipt.task_id), (new_report, task_id))
        if report == new_report or original_id == corrected_id:
            raise AssertionError('corrected revision and report require distinct identities')
        second_provenance = {
            'report_id': new_report, 'task_id': task_id, 'acceptances': [front_id, corrected_id],
            'revisions': [first_revision, corrected_revision], 'receipt': [new_report, task_id],
        }

    with closing(connect(center_path)) as reopened:
        old_result = get_review(reopened, report)
        new_result = get_review(reopened, new_report)
        emit(
            'historical',
            {'old_report': report, 'new_report': new_report, 'corrected_back': back['corrected_values']},
            {'old': old_expected, 'new': new_expected},
            {'old': counts(old_result), 'new': counts(new_result)},
            {'old': first_provenance, 'new': second_provenance},
            {'old': provenance(reopened, old_result), 'new': provenance(reopened, new_result)},
            ['ledger/revisions.py', 'station/freeze.py', 'review/issue.py', 'review/storage.py', 'review/history.py'],
            '旧读数一次，勘误后四拍均为零。重开的领取结果按两次签发前选定的接纳号和修订号核对。',
        )



def amendment_run(root, data=None):
    """Show a same-total report pair resolved by a station-side change proof.

    Mirrors ``amendment_cases.MOVED``: readings ``0,1,0,0,0,0`` move one
    crossing from pair ``(0,1)`` to ``(1,2)`` while the V1 total stays 1.
    """
    values = json.loads((Path(__file__).resolve().parent / 'examples' / 'amendment.json')
                        .read_text(encoding='utf-8'))
    layouts = (
        SegmentLayout(1, 'west', 'A', tuple(values['front']['beats'])),
        SegmentLayout(2, 'east', 'B', tuple(values['back']['beats'])),
    )
    center_path = root / 'center-amendment.sqlite'
    with closing(connect(center_path)) as center:
        initialize_catalog(center)
        initialize_intake(center)
        initialize_review(center)
        task = open_task(center, values['protocol'], values['unit'],
                         values['threshold'], values['max_change'], layouts)
        snapshot = get_task(center, task)
        exported = {}
        for slot, part, layout in zip((1, 2), (values['front'], values['back']), layouts,
                                      strict=True):
            path = root / f'amendment-station-{slot}.sqlite'
            with closing(connect(path)) as db:
                initialize_catalog(db)
                initialize_ledger(db, layout.origin)
                initialize_station(db)
                install_task_snapshot(db, snapshot)
                beats = layout.beats
                original = record_segment(db, task, slot,
                                          list(zip(beats, part['values'], strict=True)))
                old_piece = freeze_segment(db, original)
                exported[(slot, 'old')] = export_committed_segment(db, old_piece)
                corrected_values = part.get('corrected_values')
                if corrected_values is None:
                    exported[(slot, 'new')] = exported[(slot, 'old')]
                    exported[(slot, 'proof')] = None
                else:
                    corrected = record_segment(db, task, slot,
                                               list(zip(beats, corrected_values, strict=True)),
                                               parent_id=original)
                    new_piece = freeze_segment(db, corrected)
                    exported[(slot, 'new')] = export_committed_segment(db, new_piece)
                    exported[(slot, 'proof')] = export_change_proof(db, old_piece, new_piece)
        # Stations are closed from this point on.

        old_ids = [accept_committed_segment(center, *exported[(slot, 'old')]) for slot in (1, 2)]
        new_ids = [accept_committed_segment(center, *exported[(slot, 'new')]) for slot in (1, 2)]
        old_report, _ = issue_review(center, task, *old_ids)
        new_report, _ = issue_review(center, task, *new_ids)
        proofs = {slot: exported[(slot, 'proof')] for slot in (1, 2)
                  if exported[(slot, 'proof')] is not None}
        amendment_id, receipt = issue_amendment(center, old_report, new_report, proofs)
        signed = get_amendment(center, amendment_id)
        old_totals = get_review(center, old_report).total_crossings
        new_totals = get_review(center, new_report).total_crossings
        checked((old_totals, new_totals), (values['old_total'], values['new_total']))
        checked(signed['added'], tuple(map(tuple, values['added'])))
        checked(signed['removed'], tuple(map(tuple, values['removed'])))

    with closing(connect(center_path)) as reopened:
        initialize_catalog(reopened)
        initialize_intake(reopened)
        initialize_review(reopened)
        stored = get_amendment(reopened, amendment_id)
        checked(stored, signed)
        emit(
            'amendment',
            {'case': values['case'], 'old_total': old_totals, 'new_total': new_totals,
             'threshold': values['threshold'], 'max_change': values['max_change'],
             'stations_closed': True},
            {'old_total': values['old_total'], 'new_total': values['new_total'],
             'added': [list(pair) for pair in values['added']],
             'removed': [list(pair) for pair in values['removed']]},
            {'old_total': old_totals, 'new_total': new_totals,
             'added': [list(pair) for pair in signed['added']],
             'removed': [list(pair) for pair in signed['removed']]},
            {'reports': list(signed['reports']), 'acceptances': [list(pair) for pair in signed['acceptances']],
             'revisions': [list(pair) for pair in signed['revisions']],
             'proof_digests': [list(item) for item in signed['proof_digests']],
             'receipt': list(signed['receipt'])},
            {'reports': list(stored['reports']), 'acceptances': [list(pair) for pair in stored['acceptances']],
             'revisions': [list(pair) for pair in stored['revisions']],
             'proof_digests': [list(item) for item in stored['proof_digests']],
             'receipt': list(stored['receipt'])},
            ['station/evidence.py', 'intake/commitment.py', 'intake/registry.py',
             'review/amendment.py', 'review/issue.py', 'review/storage.py'],
            '两站关闭后按首纳承诺与直接勘误证明核对整段；读数 0,1,0,0,0,0 改为 0,0,1,0,0,0，'
            '总数同为 1，但告警从拍对 (0,1) 迁到 (1,2)。重开中心后按差异号取回同一签件。',
        )


def main():
    data = json.loads(SAMPLE.read_text(encoding='utf-8'))
    with TemporaryDirectory(prefix='yuwan-demo-') as folder:
        run(Path(folder), data)
    with TemporaryDirectory(prefix='yuwan-amendment-demo-') as folder:
        amendment_run(Path(folder))


if __name__ == '__main__':
    main()
