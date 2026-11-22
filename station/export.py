import json

from plan.rationals import rational_text
from .pieces import V1_FIELDS, V1_VERSION
from .storage import get_piece


def export_segment(db, piece_id):
    piece = get_piece(db, piece_id)
    values = (
        V1_VERSION, piece.origin, piece.piece_id, piece.task_id,
        piece.slot, piece.revision_id, rational_text(piece.first),
        rational_text(piece.last), piece.crossings,
    )
    payload = dict(zip(V1_FIELDS, values, strict=True))
    return json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
