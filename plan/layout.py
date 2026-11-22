from dataclasses import dataclass
from itertools import pairwise

from .protocols import require_label


@dataclass(frozen=True)
class SegmentLayout:
    slot: int
    origin: str
    rig: str
    beats: tuple[int, ...]


def validate_layout(segments):
    try:
        layouts = tuple(segments)
    except TypeError as error:
        raise ValueError('expected two ordered segment layouts') from error
    if len(layouts) != 2:
        raise ValueError('expected two ordered segment layouts')

    normalized = []
    for slot, layout in enumerate(layouts, start=1):
        if not isinstance(layout, SegmentLayout):
            raise ValueError('expected a SegmentLayout for each segment')
        if type(layout.slot) is not int or layout.slot != slot:
            raise ValueError('segment slots must be ordered 1, 2')
        require_label(layout.origin, 'station origin')
        require_label(layout.rig, 'rig')
        try:
            beats = tuple(layout.beats)
        except TypeError as error:
            raise ValueError('expected an iterable of integer beats') from error
        if not beats or any(type(beat) is not int for beat in beats):
            raise ValueError('each segment needs nonempty integer beats')
        if any(right != left + 1 for left, right in pairwise(beats)):
            raise ValueError('beats must be consecutive within a segment')
        normalized.append(SegmentLayout(slot, layout.origin, layout.rig, beats))

    front, back = normalized
    if (front.origin, front.rig) == (back.origin, back.rig):
        raise ValueError('the two segments require distinct rigs')
    if back.beats[0] != front.beats[-1] + 1:
        raise ValueError('front and back layouts must be adjacent')
    return front, back


def segment_for_slot(segments, slot):
    if type(slot) is not int or slot not in (1, 2):
        raise ValueError('segment slot must be 1 or 2')
    return segments[slot - 1]
