from dataclasses import dataclass
from fractions import Fraction

from .rationals import parse_rational


@dataclass(frozen=True)
class Protocol:
    name: str
    unit: str
    threshold: Fraction
    max_change: Fraction


def require_label(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{field} must be a nonempty string')
    try:
        value.encode('utf-8')
    except UnicodeEncodeError as error:
        raise ValueError(f'{field} must be valid UTF-8 text') from error


def make_protocol(name, unit, threshold, max_change):
    require_label(name, 'protocol name')
    require_label(unit, 'unit')
    threshold = parse_rational(threshold)
    max_change = parse_rational(max_change)
    if max_change < 0:
        raise ValueError('maximum adjacent change must be nonnegative')
    return Protocol(name, unit, threshold, max_change)
