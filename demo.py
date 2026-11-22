from contextlib import closing
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from database import connect
from intake.registry import accept_segment, get_accepted_piece, initialize_intake
from ledger.ingest import record_segment
from ledger.query import get_revision
from ledger.storage import initialize_ledger
from plan.catalog import get_task, initialize_catalog, install_task_snapshot
from plan.layout import SegmentLayout
from plan.rationals import rational_text
from plan.tasks import open_task
from review.history import get_review
from review.issue import issue_review
from review.storage import initialize_review
from station.export import export_segment
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


def main():
    data = json.loads(SAMPLE.read_text(encoding='utf-8'))
    with TemporaryDirectory(prefix='yuwan-demo-') as folder:
        run(Path(folder), data)


if __name__ == '__main__':
    main()
