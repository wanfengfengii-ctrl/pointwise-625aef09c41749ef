from ledger.query import get_revision
from plan.catalog import get_task
from .crossings import count_crossings
from .limits import check_local_limits
from .storage import save_piece


def freeze_segment(db, revision_id):
    revision = get_revision(db, revision_id)
    protocol = get_task(db, revision.task_id).protocol
    values = tuple(value for _, value in revision.samples)
    check_local_limits(values, protocol.max_change)
    crossings = count_crossings(values, protocol.threshold)
    return save_piece(db, revision, values[0], values[-1], crossings)
