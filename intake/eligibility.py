from plan.catalog import get_task
from plan.layout import segment_for_slot


def check_eligibility(db, piece):
    try:
        task = get_task(db, piece.task_id)
    except KeyError as error:
        raise ValueError('station piece refers to an unknown task') from error
    layout = segment_for_slot(task.segments, piece.slot)
    if piece.origin != layout.origin:
        raise ValueError('station piece origin does not own this segment')
    beat_count = len(layout.beats)
    if piece.crossings > beat_count // 2:
        raise ValueError('station crossing count exceeds the segment capacity')
    if beat_count == 1 and piece.first != piece.last:
        raise ValueError('a single-beat piece requires identical endpoints')
