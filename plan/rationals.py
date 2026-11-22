from fractions import Fraction


def parse_rational(value):
    """Accept exact inputs and return a reduced Fraction."""
    if isinstance(value, Fraction):
        return value
    if type(value) is int:
        return Fraction(value)
    if isinstance(value, str):
        try:
            return Fraction(value)
        except (ValueError, ZeroDivisionError) as error:
            raise ValueError('invalid rational literal') from error
    raise ValueError('expected an integer, Fraction or rational string')


def rational_text(value):
    fraction = parse_rational(value)
    return f'{fraction.numerator}/{fraction.denominator}'
