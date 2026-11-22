from dataclasses import dataclass
import json

from plan.rationals import parse_rational
from .join import SeamResult
from .storage import ReviewReceipt, read_amendment_row, read_review_rows


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


def get_amendment(db, amendment_id):
    row, proof_digests = read_amendment_row(db, amendment_id)
    (task_id, old_report_id, new_report_id,
     old_front, old_back, new_front, new_back,
     old_front_rev, old_back_rev, new_front_rev, new_back_rev,
     added, removed, receipt_task) = row
    acceptances = ((old_front, old_back), (new_front, new_back))
    revisions = (
        (old_front_rev, old_back_rev),
        (new_front_rev, new_back_rev),
    )
    return {
        'amendment_id': amendment_id,
        'task_id': task_id,
        'reports': (old_report_id, new_report_id),
        'acceptances': acceptances,
        'revisions': revisions,
        'proof_digests': tuple(proof_digests),
        'added': tuple(tuple(pair) for pair in json.loads(added)),
        'removed': tuple(tuple(pair) for pair in json.loads(removed)),
        'receipt': (amendment_id, receipt_task),
    }
