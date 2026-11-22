"""Centre-side verification of a slot's commitment pair and change proof."""
from station.crossings import is_upward_crossing
from station.evidence import (
    beat_digest, decode_change_proof, required_opening,
)
from intake.commitment import check_commitment


def _digest_map(commitment):
    return dict(commitment.beats)


def verify_slot(db, task, slot, old_piece, old_commitment, new_piece, new_commitment,
                proof_payload):
    """Check one swapped slot and return the readings settlement needs.

    Returns ``(old_values, new_values, changed)``.  Each value map holds the two
    public endpoints and every internal beat the proof opened; ``changed`` lists
    every beat whose reading differs between the two commitments.
    """
    layout = task.segments[slot - 1]
    if old_piece.slot != slot or new_piece.slot != slot:
        raise ValueError('selected piece falls outside its report slot')
    if old_piece.task_id != task.task_id or new_piece.task_id != task.task_id:
        raise ValueError('selected piece belongs to another task')

    proof = decode_change_proof(proof_payload)
    if (proof.task_id, proof.origin, proof.slot) != (
            old_piece.task_id, old_piece.origin, old_piece.slot):
        raise ValueError('change proof does not describe the selected segment')
    if (proof.old_piece_id, proof.old_revision_id) != (
            old_piece.piece_id, old_piece.revision_id):
        raise ValueError('change proof does not open the old station piece')
    if (proof.new_piece_id, proof.new_revision_id) != (
            new_piece.piece_id, new_piece.revision_id):
        raise ValueError('change proof does not open the new station piece')

    check_commitment(db, old_piece, old_commitment)
    check_commitment(db, new_piece, new_commitment)
    if new_commitment.parent_revision_id != old_piece.revision_id:
        raise ValueError('the new piece is not a direct correction of the old one')

    beats = tuple(layout.beats)
    old_digests = _digest_map(old_commitment)
    new_digests = _digest_map(new_commitment)
    if tuple(old_digests) != beats or tuple(new_digests) != beats:
        raise ValueError('commitments must cover the planned segment in plan order')

    changed = [beat for beat in beats if old_digests[beat] != new_digests[beat]]
    required = required_opening(beats, changed)
    opened = {value.beat for value in proof.values}
    if opened != required:
        raise ValueError('change proof opens the wrong set of internal beats')
    if opened - set(beats):
        raise ValueError('change proof reading lies outside the segment')

    old_values = {beats[0]: old_piece.first, beats[-1]: old_piece.last}
    new_values = {beats[0]: new_piece.first, beats[-1]: new_piece.last}
    for value in proof.values:
        if beat_digest(old_piece.task_id, old_piece.origin, old_piece.slot,
                       value.beat, value.old) != old_digests[value.beat]:
            raise ValueError('change proof old reading contradicts its commitment')
        if beat_digest(new_piece.task_id, new_piece.origin, new_piece.slot,
                       value.beat, value.new) != new_digests[value.beat]:
            raise ValueError('change proof new reading contradicts its commitment')
        old_values[value.beat] = value.old
        new_values[value.beat] = value.new

    return old_values, new_values, changed


def _affected_pairs(beats, changed):
    pairs = set()
    for beat in changed:
        if beat - 1 in beats:
            pairs.add((beat - 1, beat))
        if beat + 1 in beats:
            pairs.add((beat, beat + 1))
    return pairs


def settle(task, old_pieces, new_pieces, slot_values):
    """Return ascending added and removed adjacent pairs for the whole plan.

    ``slot_values`` maps slot to ``(old_values, new_values, changed)``.
    """
    threshold = task.protocol.threshold
    added = []
    removed = []
    for slot in (1, 2):
        beats = set(task.segments[slot - 1].beats)
        old_values, new_values, changed = slot_values[slot]
        for left, right in _affected_pairs(beats, changed):
            try:
                old_before, old_after = old_values[left], old_values[right]
                new_before, new_after = new_values[left], new_values[right]
            except KeyError as error:
                raise ValueError('change proof omits an internal neighbour') from error
            was = is_upward_crossing(old_before, old_after, threshold)
            now = is_upward_crossing(new_before, new_after, threshold)
            if now and not was:
                added.append((left, right))
            elif was and not now:
                removed.append((left, right))

    seam = (task.segments[0].beats[-1], task.segments[1].beats[0])
    was = is_upward_crossing(old_pieces[0].piece.last, old_pieces[1].piece.first, threshold)
    now = is_upward_crossing(new_pieces[0].piece.last, new_pieces[1].piece.first, threshold)
    if now and not was:
        added.append(seam)
    elif was and not now:
        removed.append(seam)

    return tuple(sorted(added)), tuple(sorted(removed))
