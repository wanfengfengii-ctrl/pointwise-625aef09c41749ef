"""V1 comparison fixtures and hand-counted outcomes for amendment checks."""
from contextlib import ExitStack, closing
from dataclasses import dataclass
import json

from database import connect
from intake.registry import accept_segment, initialize_intake
from ledger.ingest import record_segment
from ledger.storage import initialize_ledger
from plan.catalog import get_task, initialize_catalog, install_task_snapshot
from plan.layout import SegmentLayout
from plan.tasks import open_task
from review.history import get_review
from review.issue import issue_review
from review.storage import initialize_review
from station.export import export_segment
from station.freeze import freeze_segment
from station.storage import initialize_station


@dataclass(frozen=True)
class Case:
    name: str
    old: tuple[tuple[int, ...], tuple[int, ...]]
    corrected: tuple[tuple[int, ...] | None, tuple[int, ...] | None]
    totals: tuple[int, int]
    added: tuple[tuple[int, int], ...]
    removed: tuple[tuple[int, int], ...]


MOVED = Case(
    "same-total-moved-crossing", ((0, 1, 0, 0, 0, 0), (0,)),
    ((0, 0, 1, 0, 0, 0), None), (1, 1), ((1, 2),), ((0, 1),),
)
NO_CHANGE = Case(
    "direct-correction-without-value-change", MOVED.old, (MOVED.old[0], None),
    (1, 1), (), (),
)
SEAM = Case(
    "both-sides-of-seam", ((0, 0), (1, 1)), ((0, 1), (0, 1)),
    (1, 2), ((0, 1), (2, 3)), ((1, 2),),
)


def prepare_case(center, stations, case):
    """Return the task and the old/new V1 piece numbers for each slot."""
    initialize_catalog(center)
    initialize_intake(center)
    initialize_review(center)
    split = len(case.old[0])
    layouts = (
        SegmentLayout(1, "west", "front-rig", tuple(range(split))),
        SegmentLayout(2, "east", "back-rig", tuple(range(split, split + len(case.old[1])))),
    )
    task_id = open_task(center, "Yuwan amendment check", "kN", 1, 1, layouts)
    snapshot = get_task(center, task_id)
    pairs = []
    for db, layout, initial, corrected in zip(stations, layouts, case.old, case.corrected, strict=True):
        initialize_catalog(db)
        initialize_ledger(db, layout.origin)
        initialize_station(db)
        install_task_snapshot(db, snapshot)
        revision = record_segment(db, task_id, layout.slot, zip(layout.beats, initial, strict=True))
        old_piece = freeze_segment(db, revision)
        new_piece = old_piece
        if corrected is not None:
            replacement = record_segment(
                db, task_id, layout.slot, zip(layout.beats, corrected, strict=True), parent_id=revision,
            )
            new_piece = freeze_segment(db, replacement)
        pairs.append((old_piece, new_piece))
    return task_id, tuple(pairs)


def run_v1(case):
    with closing(connect(":memory:")) as center:
        with ExitStack() as stations_open:
            stations = tuple(stations_open.enter_context(closing(connect(":memory:"))) for _ in case.old)
            task_id, pieces = prepare_case(center, stations, case)
            wire_by_slot = tuple(
                tuple(export_segment(db, piece) for piece in pair)
                for db, pair in zip(stations, pieces, strict=True)
            )
        accepted_by_slot = tuple(
            tuple(accept_segment(center, wire) for wire in pair) for pair in wire_by_slot
        )
        reports = tuple(
            get_review(center, issue_review(center, task_id, *selected)[0])
            for selected in zip(*accepted_by_slot, strict=True)
        )
        totals = tuple(report.total_crossings for report in reports)
        if totals != case.totals:
            raise AssertionError(f"{case.name}: expected totals {case.totals}, got {totals}")
        return wire_by_slot, reports


def main():
    moved = run_v1(MOVED)
    unchanged = run_v1(NO_CHANGE)
    if moved != unchanged:
        raise AssertionError("V1 should produce identical station bytes and reports in both worlds")
    seam = run_v1(SEAM)
    for case, (_, reports) in ((MOVED, moved), (NO_CHANGE, unchanged), (SEAM, seam)):
        print(json.dumps({
            "case": case.name,
            "v1_totals": [report.total_crossings for report in reports],
            "hand_counted_added": case.added,
            "hand_counted_removed": case.removed,
        }))


if __name__ == "__main__":
    main()
