from itertools import pairwise


def check_local_limits(values, max_change):
    for index, (before, after) in enumerate(pairwise(values), start=1):
        if abs(after - before) > max_change:
            raise ValueError(f'adjacent change exceeds the limit at sample pair {index}')
