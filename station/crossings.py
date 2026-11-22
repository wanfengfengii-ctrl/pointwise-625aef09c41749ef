from itertools import pairwise


def is_upward_crossing(before, after, threshold):
    return before < threshold <= after


def count_crossings(values, threshold):
    return sum(is_upward_crossing(before, after, threshold) for before, after in pairwise(values))
