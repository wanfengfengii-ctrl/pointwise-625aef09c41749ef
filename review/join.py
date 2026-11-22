from dataclasses import dataclass
from fractions import Fraction

from station.crossings import is_upward_crossing


@dataclass(frozen=True)
class SeamResult:
    before: Fraction
    after: Fraction
    change: Fraction
    crossings: int


def evaluate_seam(protocol, front, back):
    before, after = front.last, back.first
    change = abs(after - before)
    if change > protocol.max_change:
        raise ValueError('seam change exceeds the limit')
    crossings = int(is_upward_crossing(before, after, protocol.threshold))
    return SeamResult(before, after, change, crossings)


def total_crossings(front, back, seam):
    return front.crossings + back.crossings + seam.crossings
