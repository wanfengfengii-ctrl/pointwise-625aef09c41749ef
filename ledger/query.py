from dataclasses import dataclass
from fractions import Fraction

from .storage import read_revision_header, read_revision_samples


@dataclass(frozen=True)
class ReadingRevision:
    revision_id: int
    task_id: int
    slot: int
    origin: str
    rig: str
    parent_id: int | None
    samples: tuple[tuple[int, Fraction], ...]


def get_revision(db, revision_id):
    header = read_revision_header(db, revision_id)
    samples = read_revision_samples(db, revision_id)
    return ReadingRevision(revision_id, *header, samples)
