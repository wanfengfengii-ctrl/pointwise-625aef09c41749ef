import json

from database import is_key
from plan.protocols import require_label
from plan.rationals import parse_rational, rational_text
from station.pieces import StationPiece, V1_FIELDS, V1_VERSION


def _unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError(f'duplicate station piece field: {key}')
        obj[key] = value
    return obj


def _wire_rational(raw):
    if not isinstance(raw, str):
        raise ValueError('station endpoints must be rational strings')
    value = parse_rational(raw)
    if rational_text(value) != raw:
        raise ValueError('station endpoints must use reduced numerator/denominator text')
    return value


def decode_v1(payload):
    if not isinstance(payload, bytes):
        raise ValueError('a station piece must be UTF-8 JSON bytes')
    try:
        data = json.loads(payload.decode('utf-8'), object_pairs_hook=_unique_object)
    except (ValueError, RecursionError) as error:
        raise ValueError('invalid station piece JSON') from error
    if type(data) is not dict or data.keys() != set(V1_FIELDS):
        raise ValueError('unexpected V1 station piece fields')
    if type(data['version']) is not int or data['version'] != V1_VERSION:
        raise ValueError('unsupported station piece version')
    require_label(data['origin'], 'station origin')
    for field in ('piece_id', 'task_id', 'revision_id'):
        if not is_key(data[field]):
            raise ValueError(f'invalid station piece {field}')
    if type(data['slot']) is not int or data['slot'] not in (1, 2):
        raise ValueError('invalid station piece slot')
    if type(data['crossings']) is not int or data['crossings'] < 0:
        raise ValueError('invalid station crossing count')
    return StationPiece(
        data['origin'], data['piece_id'], data['task_id'], data['slot'],
        data['revision_id'], _wire_rational(data['first']),
        _wire_rational(data['last']), data['crossings'],
    )
