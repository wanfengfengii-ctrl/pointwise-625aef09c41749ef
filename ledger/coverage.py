from plan.rationals import parse_rational


def validate_coverage(layout, samples):
    try:
        entries = iter(samples)
    except TypeError as error:
        raise ValueError('samples must be an iterable of beat and value pairs') from error

    readings = {}
    planned = set(layout.beats)
    for entry in entries:
        try:
            beat, value = entry
        except (TypeError, ValueError) as error:
            raise ValueError('a sample must contain one beat and one value') from error
        if type(beat) is not int or beat not in planned:
            raise ValueError('sample beat falls outside the segment layout')
        if beat in readings:
            raise ValueError('duplicate sample beat')
        readings[beat] = parse_rational(value)
    if readings.keys() != planned:
        raise ValueError('samples must cover every planned beat')
    return tuple((beat, readings[beat]) for beat in layout.beats)
