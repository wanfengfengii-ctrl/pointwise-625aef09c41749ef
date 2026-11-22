from plan.catalog import get_task
from plan.layout import segment_for_slot
from .coverage import validate_coverage
from .revisions import correction_parent
from .storage import insert_revision, ledger_origin


def record_segment(db, task_id, slot, samples, parent_id=None):
    task = get_task(db, task_id)
    layout = segment_for_slot(task.segments, slot)
    if ledger_origin(db) != layout.origin:
        raise ValueError('this station does not own the requested segment')
    parent = correction_parent(db, task.task_id, layout, parent_id)
    checked_samples = validate_coverage(layout, samples)
    return insert_revision(db, task.task_id, layout, checked_samples, parent)
