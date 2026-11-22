"""Centre-side checks binding a segment commitment to a V1 station piece."""
from plan.catalog import get_task
from plan.layout import segment_for_slot
from station.evidence import beat_digest


def check_commitment(db, piece, commitment):
    """Verify a commitment's structure, task scope and piece binding.

    The whole planned segment must be covered in plan order and both published
    V1 endpoints must hash to the commitment.  Internal readings stay hidden.
    """
    try:
        task = get_task(db, piece.task_id)
    except KeyError as error:
        raise ValueError('commitment refers to an unknown task') from error
    layout = segment_for_slot(task.segments, piece.slot)
    if commitment.task_id != piece.task_id:
        raise ValueError('commitment task does not match the station piece')
    if commitment.origin != piece.origin or commitment.origin != layout.origin:
        raise ValueError('commitment origin does not own this segment')
    if commitment.slot != piece.slot:
        raise ValueError('commitment slot does not match the station piece')
    if commitment.piece_id != piece.piece_id:
        raise ValueError('commitment does not describe this station piece')
    if commitment.revision_id != piece.revision_id:
        raise ValueError('commitment revision does not match the station piece')
    if commitment.parent_revision_id == commitment.revision_id:
        raise ValueError('a revision cannot be its own parent')
    positions = tuple(beat for beat, _ in commitment.beats)
    if positions != tuple(layout.beats):
        raise ValueError('commitment must cover the whole planned segment in plan order')

    first_beat, last_beat = layout.beats[0], layout.beats[-1]
    by_beat = dict(commitment.beats)
    if by_beat[first_beat] != beat_digest(
            piece.task_id, piece.origin, piece.slot, first_beat, piece.first):
        raise ValueError('commitment does not match the published first reading')
    if by_beat[last_beat] != beat_digest(
            piece.task_id, piece.origin, piece.slot, last_beat, piece.last):
        raise ValueError('commitment does not match the published last reading')
    return task, layout
