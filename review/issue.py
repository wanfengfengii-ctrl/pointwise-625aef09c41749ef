from .join import evaluate_seam, total_crossings
from .selection import select_pieces
from .storage import save_review


def issue_review(db, task_id, front_id, back_id, *, before_commit=None):
    selection = select_pieces(db, task_id, front_id, back_id)
    front = selection.front.piece
    back = selection.back.piece
    seam = evaluate_seam(selection.task.protocol, front, back)
    total = total_crossings(front, back, seam)
    return save_review(db, selection, seam, total, before_commit=before_commit)
