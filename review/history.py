from dataclasses import dataclass

from plan.rationals import parse_rational
from .join import SeamResult
from .storage import ReviewReceipt, read_review_rows


@dataclass(frozen=True)
class ReviewResult:
    report_id: int
    task_id: int
    front_id: int
    back_id: int
    front_crossings: int
    back_crossings: int
    seam: SeamResult
    total_crossings: int
    receipt: ReviewReceipt


def get_review(db, report_id):
    fields, receipt = read_review_rows(db, report_id)
    task_id, front_id, back_id, front_count, back_count, before, after, change, seam_count, total = fields
    seam = SeamResult(parse_rational(before), parse_rational(after), parse_rational(change), seam_count)
    return ReviewResult(
        report_id, task_id, front_id, back_id, front_count, back_count, seam, total, receipt,
    )
