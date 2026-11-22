"""Wire encoding for segment commitments and direct-change proofs.

Both documents are UTF-8 JSON objects.  Beat positions are the integers from
the task catalogue; readings are reduced ``numerator/denominator`` strings.
Commitments expose one SHA-256 digest per planned beat.  A digest is computed
deterministically from the task, station, slot, beat position and reduced
reading, so equal readings at the same planned position collide by design and
the centre can tell which beats changed between two revisions without opening
unchanged ones.  The digest itself reveals only a hash of a small rational, so
commitments are comparison material rather than a secrecy mechanism.  A proof
opens just the changed beats and the internal neighbouring beats needed to
settle the adjacent pairs; the V1 published endpoints are checked against the
commitment instead of being repeated.

This module only encodes, decodes and hashes evidence.  Cross-checking a
document against a station piece, a task layout or another piece belongs to the
station export and the centre intake layers.
"""
from dataclasses import dataclass
from fractions import Fraction
import hashlib
import json

from database import is_key
from plan.rationals import parse_rational, rational_text


COMMITMENT_KIND = 'segment-commitment'
PROOF_KIND = 'change-proof'
EVIDENCE_VERSION = 1
COMMITMENT_FIELDS = frozenset({
    'version', 'kind', 'origin', 'piece_id', 'task_id', 'slot',
    'revision_id', 'parent_revision_id', 'beats',
})
PROOF_FIELDS = frozenset({
    'version', 'kind', 'task_id', 'origin', 'slot', 'old', 'new', 'values',
})
PROOF_SIDE_FIELDS = frozenset({'piece_id', 'revision_id'})
_HEX_DIGITS = frozenset('0123456789abcdef')


@dataclass(frozen=True)
class SegmentCommitment:
    origin: str
    piece_id: int
    task_id: int
    slot: int
    revision_id: int
    parent_revision_id: int | None
    beats: tuple[tuple[int, str], ...]


@dataclass(frozen=True)
class ProofValue:
    beat: int
    old: Fraction
    new: Fraction


@dataclass(frozen=True)
class ChangeProof:
    task_id: int
    origin: str
    slot: int
    old_piece_id: int
    old_revision_id: int
    new_piece_id: int
    new_revision_id: int
    values: tuple[ProofValue, ...]


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8')


def _unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError(f'duplicate evidence field: {key}')
        obj[key] = value
    return obj


def _load_object(payload, label):
    if not isinstance(payload, bytes):
        raise ValueError(f'{label} must be UTF-8 JSON bytes')
    try:
        data = json.loads(payload.decode('utf-8'), object_pairs_hook=_unique_object)
    except (ValueError, RecursionError) as error:
        raise ValueError(f'invalid {label} JSON') from error
    if type(data) is not dict:
        raise ValueError(f'{label} must be a JSON object')
    return data


def _require_digest(value, label):
    if (not isinstance(value, str) or len(value) != 64
            or not set(value) <= _HEX_DIGITS):
        raise ValueError(f'{label} must be a lowercase SHA-256 hex digest')
    return value


def _decode_rational_text(raw, label):
    if not isinstance(raw, str):
        raise ValueError(f'{label} must be a rational string')
    value = parse_rational(raw)
    if rational_text(value) != raw:
        raise ValueError(f'{label} must use reduced numerator/denominator text')
    return value


def _require_origin(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('evidence origin must be a nonempty string')
    try:
        value.encode('utf-8')
    except UnicodeEncodeError as error:
        raise ValueError('evidence origin must be valid UTF-8 text') from error
    return value


def _require_slot(value):
    if type(value) is not int or value not in (1, 2):
        raise ValueError('evidence slot must be 1 or 2')
    return value


def beat_digest(task_id, origin, slot, beat, value):
    """Digest one reading at its planned beat position."""
    text = rational_text(parse_rational(value))
    return hashlib.sha256(canonical_json(
        ['yuwan-commit-value-v1', task_id, origin, slot, beat, text]
    )).hexdigest()


def encode_commitment(commitment):
    body = {
        'version': EVIDENCE_VERSION,
        'kind': COMMITMENT_KIND,
        'origin': commitment.origin,
        'piece_id': commitment.piece_id,
        'task_id': commitment.task_id,
        'slot': commitment.slot,
        'revision_id': commitment.revision_id,
        'parent_revision_id': commitment.parent_revision_id,
        'beats': [[beat, digest] for beat, digest in commitment.beats],
    }
    return canonical_json(body)


def decode_commitment(payload):
    data = _load_object(payload, 'segment commitment')
    if set(data) != COMMITMENT_FIELDS:
        raise ValueError('unexpected segment commitment fields')
    if type(data['version']) is not int or data['version'] != EVIDENCE_VERSION:
        raise ValueError('unsupported segment commitment version')
    if data['kind'] != COMMITMENT_KIND:
        raise ValueError('unexpected segment commitment kind')
    origin = _require_origin(data['origin'])
    for field in ('piece_id', 'task_id', 'revision_id'):
        if not is_key(data[field]):
            raise ValueError(f'invalid segment commitment {field}')
    slot = _require_slot(data['slot'])
    parent = data['parent_revision_id']
    if parent is not None and not is_key(parent):
        raise ValueError('invalid segment commitment parent revision')
    raw_beats = data['beats']
    if not isinstance(raw_beats, list) or not raw_beats:
        raise ValueError('a commitment must cover every planned beat')
    beats = []
    seen = set()
    for entry in raw_beats:
        if not isinstance(entry, list) or len(entry) != 2:
            raise ValueError('a commitment beat must pair a position and digest')
        beat, digest = entry
        if type(beat) is not int:
            raise ValueError('a commitment beat position must be an integer')
        if beat in seen:
            raise ValueError('duplicate commitment beat position')
        seen.add(beat)
        beats.append((beat, _require_digest(digest, 'commitment beat digest')))
    return SegmentCommitment(
        origin, data['piece_id'], data['task_id'], slot, data['revision_id'],
        parent, tuple(beats),
    )


def encode_change_proof(proof):
    body = {
        'version': EVIDENCE_VERSION,
        'kind': PROOF_KIND,
        'task_id': proof.task_id,
        'origin': proof.origin,
        'slot': proof.slot,
        'old': {
            'piece_id': proof.old_piece_id,
            'revision_id': proof.old_revision_id,
        },
        'new': {
            'piece_id': proof.new_piece_id,
            'revision_id': proof.new_revision_id,
        },
        'values': [
            [value.beat, rational_text(value.old), rational_text(value.new)]
            for value in proof.values
        ],
    }
    return canonical_json(body)


def _decode_proof_side(data, label):
    if type(data) is not dict or set(data) != PROOF_SIDE_FIELDS:
        raise ValueError(f'unexpected change proof {label} fields')
    if not is_key(data['piece_id']) or not is_key(data['revision_id']):
        raise ValueError(f'invalid change proof {label} identity')
    return data['piece_id'], data['revision_id']


def decode_change_proof(payload):
    data = _load_object(payload, 'change proof')
    if set(data) != PROOF_FIELDS:
        raise ValueError('unexpected change proof fields')
    if type(data['version']) is not int or data['version'] != EVIDENCE_VERSION:
        raise ValueError('unsupported change proof version')
    if data['kind'] != PROOF_KIND:
        raise ValueError('unexpected change proof kind')
    if not is_key(data['task_id']):
        raise ValueError('invalid change proof task')
    origin = _require_origin(data['origin'])
    slot = _require_slot(data['slot'])
    old_piece, old_revision = _decode_proof_side(data['old'], 'old')
    new_piece, new_revision = _decode_proof_side(data['new'], 'new')
    raw_values = data['values']
    if not isinstance(raw_values, list):
        raise ValueError('change proof values must be a list')
    values = []
    seen = set()
    for entry in raw_values:
        if not isinstance(entry, list) or len(entry) != 3:
            raise ValueError('a proof value must pair a beat with two readings')
        beat, old_text, new_text = entry
        if type(beat) is not int:
            raise ValueError('a proof beat position must be an integer')
        if beat in seen:
            raise ValueError('duplicate proof beat position')
        seen.add(beat)
        values.append(ProofValue(
            beat,
            _decode_rational_text(old_text, 'proof old reading'),
            _decode_rational_text(new_text, 'proof new reading'),
        ))
    return ChangeProof(
        data['task_id'], origin, slot, old_piece, old_revision,
        new_piece, new_revision, tuple(values),
    )


def commitment_for(piece, values, parent_revision_id=None):
    """Build the commitment document for a frozen piece and its readings."""
    if parent_revision_id is not None and not is_key(parent_revision_id):
        raise ValueError('invalid commitment parent revision')
    return SegmentCommitment(
        piece.origin, piece.piece_id, piece.task_id, piece.slot,
        piece.revision_id, parent_revision_id, tuple(
            (beat, beat_digest(piece.task_id, piece.origin, piece.slot, beat, value))
            for beat, value in values
        ),
    )


def changed_beats(old_values, new_values):
    """Return the beats whose readings differ between two aligned segments."""
    if len(old_values) != len(new_values):
        raise ValueError('both revisions must cover the same planned beats')
    changed = []
    for (beat, old), (other_beat, new) in zip(old_values, new_values, strict=True):
        if beat != other_beat:
            raise ValueError('both revisions must cover the same planned beats')
        if old != new:
            changed.append(beat)
    return changed


def required_opening(beats, changed):
    """Beats a proof must open: changes plus their internal neighbours.

    Segment endpoints are published by the V1 piece fields and are checked
    against the commitment, so they are never opened in a proof.  Only at most
    the two edges touching a changed beat can alter their crossing status.
    """
    first, last = beats[0], beats[-1]
    endpoints = (first, last)
    opened = set()
    for beat in changed:
        if beat not in endpoints:
            opened.add(beat)
        for neighbour in (beat - 1, beat + 1):
            if neighbour in beats and neighbour not in endpoints:
                opened.add(neighbour)
    return opened


def proof_for(piece_old, old_values, piece_new, new_values):
    """Build the direct-change proof over the changed beats and their neighbours."""
    beats = tuple(beat for beat, _ in old_values)
    changed = changed_beats(old_values, new_values)
    opening = required_opening(beats, changed)
    old_by_beat = dict(old_values)
    new_by_beat = dict(new_values)
    ordered = sorted(opening)
    return ChangeProof(
        piece_old.task_id, piece_old.origin, piece_old.slot,
        piece_old.piece_id, piece_old.revision_id,
        piece_new.piece_id, piece_new.revision_id,
        tuple(ProofValue(beat, old_by_beat[beat], new_by_beat[beat]) for beat in ordered),
    )

