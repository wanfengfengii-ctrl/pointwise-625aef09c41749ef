from dataclasses import dataclass
from fractions import Fraction


V1_VERSION = 1
V1_FIELDS = (
    'version', 'origin', 'piece_id', 'task_id', 'slot', 'revision_id',
    'first', 'last', 'crossings',
)


@dataclass(frozen=True)
class StationPiece:
    origin: str
    piece_id: int
    task_id: int
    slot: int
    revision_id: int
    first: Fraction
    last: Fraction
    crossings: int
