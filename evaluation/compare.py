"""Automatic comparison operators (TEST_PROTOCOL section 6)."""
from decimal import Decimal, InvalidOperation

MISSING = object()


def resolve_pointer(document, pointer):
    node = document
    for raw in pointer.lstrip('/').split('/'):
        token = raw.replace('~1', '/').replace('~0', '~')
        if isinstance(node, dict) and token in node:
            node = node[token]
        elif isinstance(node, list) and token.isdigit() and int(token) < len(node):
            node = node[int(token)]
        else:
            return MISSING
    return node


def _decimal(value):
    if isinstance(value, bool) or value is None:
        raise TypeError('not a number')
    result = Decimal(str(value))
    if not result.is_finite():
        raise TypeError('not finite')
    return result


def _is_number(value):
    return isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)


def equal(actual, expected):
    if isinstance(expected, bool) or isinstance(actual, bool) or expected is None or actual is None:
        return type(actual) is type(expected) and actual == expected
    return actual == expected


def decimal_equal(actual, expected):
    if expected is None or actual is None:
        return actual is None and expected is None
    try:
        value = _decimal(actual)
    except (TypeError, InvalidOperation):
        return False
    if value.as_tuple().exponent < -2:
        return False
    return value == _decimal(expected)


def _element_equal(actual, expected):
    if _is_number(expected):
        try:
            return _decimal(actual) == _decimal(expected)
        except (TypeError, InvalidOperation):
            return False
    return equal(actual, expected)


def ordered_equal(actual, expected):
    return (isinstance(actual, list) and isinstance(expected, list) and len(actual) == len(expected)
            and all(_element_equal(a, e) for a, e in zip(actual, expected)))


def set_equal(actual, expected):
    if not isinstance(actual, list) or not isinstance(expected, list):
        return False
    if len(actual) != len({repr(a) for a in actual}):
        return False
    return len(actual) == len(expected) and all(any(_element_equal(a, e) for a in actual) for e in expected)


def less_than_or_equal(actual, expected):
    try:
        return _decimal(actual) <= _decimal(expected)
    except (TypeError, InvalidOperation):
        return False


OPERATORS = {'equal': equal, 'decimal_equal': decimal_equal, 'ordered_equal': ordered_equal,
             'set_equal': set_equal, 'less_than_or_equal': less_than_or_equal}


def evaluate_checks(envelope, checks):
    results = []
    for check in checks:
        actual = resolve_pointer(envelope, check['path'])
        if actual is MISSING:
            passed, actual_out = False, '<missing>'
        else:
            passed, actual_out = OPERATORS[check['operator']](actual, check['expected']), actual
        results.append({'path': check['path'], 'operator': check['operator'], 'expected': check['expected'],
                        'actual': actual_out, 'passed': passed})
    return results
