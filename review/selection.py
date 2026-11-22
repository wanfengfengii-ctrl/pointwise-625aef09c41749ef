from dataclasses import dataclass

from intake.registry import AcceptedPiece, get_accepted_piece
from plan.catalog import TaskSnapshot, get_task


@dataclass(frozen=True)
class ReviewSelection:
    task: TaskSnapshot
    front: AcceptedPiece
    back: AcceptedPiece


def select_pieces(db, task_id, front_id, back_id):
    task = get_task(db, task_id)
    front = get_accepted_piece(db, front_id)
    back = get_accepted_piece(db, back_id)
    if front_id == back_id:
        raise ValueError('two distinct acceptances are required')
    if front.piece.task_id != task_id or back.piece.task_id != task_id:
        raise ValueError('both pieces must belong to the requested task')
    if (front.piece.slot, back.piece.slot) != (1, 2):
        raise ValueError('pieces must be selected in front, back order')
    return ReviewSelection(task, front, back)
