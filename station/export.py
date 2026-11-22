import json

from ledger.query import get_revision
from plan.rationals import rational_text
from .evidence import (
    commitment_for, encode_change_proof, encode_commitment, proof_for,
)
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


def export_committed_segment(db, piece_id):
    """Return the V1 payload plus the commitment over the whole frozen segment."""
    payload = export_segment(db, piece_id)
    piece = get_piece(db, piece_id)
    revision = get_revision(db, piece.revision_id)
    commitment = commitment_for(piece, revision.samples, revision.parent_id)
    return payload, encode_commitment(commitment)


def export_change_proof(db, old_piece_id, new_piece_id):
    """Return the direct-change proof between two successive frozen pieces."""
    old_piece = get_piece(db, old_piece_id)
    new_piece = get_piece(db, new_piece_id)
    if old_piece.task_id != new_piece.task_id:
        raise ValueError('both pieces must belong to the same task')
    if (old_piece.slot, old_piece.origin) != (new_piece.slot, new_piece.origin):
        raise ValueError('both pieces must belong to the same segment')
    if (old_piece.origin, old_piece.revision_id) == (new_piece.origin, new_piece.revision_id):
        raise ValueError('a change proof requires two distinct frozen revisions')
    old_revision = get_revision(db, old_piece.revision_id)
    new_revision = get_revision(db, new_piece.revision_id)
    if new_revision.parent_id != old_revision.revision_id:
        raise ValueError('the new revision must be a direct correction of the old one')
    proof = proof_for(old_piece, old_revision.samples, new_piece, new_revision.samples)
    return encode_change_proof(proof)
