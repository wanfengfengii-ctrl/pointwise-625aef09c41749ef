from hashlib import sha256

from intake.registry import get_committed_piece
from plan.catalog import get_task
from .amendment import settle, verify_slot
from .history import get_review
from .join import evaluate_seam, total_crossings
from .selection import select_pieces
from .storage import save_amendment, save_review


def issue_review(db, task_id, front_id, back_id, *, before_commit=None):
    selection = select_pieces(db, task_id, front_id, back_id)
    front = selection.front.piece
    back = selection.back.piece
    seam = evaluate_seam(selection.task.protocol, front, back)
    total = total_crossings(front, back, seam)
    return save_review(db, selection, seam, total, before_commit=before_commit)


def _endpoint_values(piece, beats):
    return {beats[0]: piece.first, beats[-1]: piece.last}


def issue_amendment(db, old_report_id, new_report_id, proofs, *, before_commit=None):
    if not isinstance(proofs, dict):
        raise ValueError('proofs must map swapped slots to proof bytes')
    old_report = get_review(db, old_report_id)
    new_report = get_review(db, new_report_id)
    if old_report_id == new_report_id:
        raise ValueError('two distinct reports are required')
    if old_report.task_id != new_report.task_id:
        raise ValueError('both reports must belong to the same task')
    task = get_task(db, old_report.task_id)

    slot_pairs = (
        (old_report.front_id, new_report.front_id),
        (old_report.back_id, new_report.back_id),
    )
    swapped = {slot for slot, (old_id, new_id) in enumerate(slot_pairs, start=1)
               if old_id != new_id}
    if any(type(slot) is not int for slot in proofs):
        raise ValueError('proof slots must be integer segment positions')
    if set(proofs) != swapped:
        raise ValueError('proof slots must exactly match the swapped segments')
    for slot in swapped:
        if not isinstance(proofs[slot], bytes):
            raise ValueError('a change proof must be bytes')

    old_pieces = []
    new_pieces = []
    slot_values = {}
    digests = {}
    for slot, (old_id, new_id) in enumerate(slot_pairs, start=1):
        beats = task.segments[slot - 1].beats
        old = get_committed_piece(db, old_id)
        new = get_committed_piece(db, new_id)
        old_pieces.append(old)
        new_pieces.append(new)
        if slot in swapped:
            old_values, new_values, changed = verify_slot(
                db, task, slot, old.piece, old.commitment,
                new.piece, new.commitment, proofs[slot],
            )
            digests[slot] = sha256(proofs[slot]).hexdigest()
        else:
            old_values = _endpoint_values(old.piece, beats)
            new_values = dict(old_values)
            changed = ()
        slot_values[slot] = (old_values, new_values, changed)

    added, removed = settle(task, old_pieces, new_pieces, slot_values)
    acceptances = (
        (old_report.front_id, old_report.back_id),
        (new_report.front_id, new_report.back_id),
    )
    revisions = (
        (old_pieces[0].piece.revision_id, old_pieces[1].piece.revision_id),
        (new_pieces[0].piece.revision_id, new_pieces[1].piece.revision_id),
    )
    return save_amendment(
        db, task.task_id, old_report_id, new_report_id, acceptances, revisions,
        digests, added, removed, before_commit=before_commit,
    )
