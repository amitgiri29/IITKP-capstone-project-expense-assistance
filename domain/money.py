"""Decimal money helpers. Floats never enter a calculation."""
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from domain.registry import parameter

_ROUNDING_MODES = {'ROUND_HALF_UP': ROUND_HALF_UP}


def to_decimal(value):
    """Convert JSON input to Decimal. None stays None; booleans and non-finite values are rejected."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError('boolean is not an amount')
    try:
        result = Decimal(str(value).strip().replace(',', ''))
    except InvalidOperation as exc:
        raise ValueError('not a decimal amount: %r' % (value,)) from exc
    if not result.is_finite():
        raise ValueError('amount must be finite')
    return result


def quantum():
    return Decimal(1).scaleb(-parameter('PARAM-MONEY-SCALE'))


def round_money(value):
    mode = _ROUNDING_MODES[parameter('PARAM-MONEY-ROUNDING')]
    return value.quantize(quantum(), rounding=mode)


def money_str(value):
    """Two-place decimal string for output, or None for an unknown amount."""
    return None if value is None else str(round_money(value))


def zero():
    return Decimal(0)
