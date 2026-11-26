"""Evaluator operators (TEST_PROTOCOL section 6)."""
from evaluation.compare import MISSING, decimal_equal, equal, ordered_equal, resolve_pointer, set_equal


def test_equal_is_type_aware():
    assert not equal(False, None) and not equal(0, False) and equal(None, None)


def test_decimal_equal_accepts_strings_and_rejects_extra_precision():
    assert decimal_equal('22260.00', 22260.0) and decimal_equal('1.70', 1.7)
    assert not decimal_equal('1.705', 1.705) and not decimal_equal(None, 0)


def test_ordered_and_set_equal():
    assert ordered_equal(['0.85', '0.85'], [0.85, 0.85]) and not ordered_equal(['H2', 'H1'], ['H1', 'H2'])
    assert set_equal(['H1', 'H2'], ['H2', 'H1']) and not set_equal(['H1', 'H1'], ['H1', 'H1'])


def test_missing_pointer_is_distinct_from_null():
    assert resolve_pointer({'result': {'a': None}}, '/result/a') is None
    assert resolve_pointer({'result': {}}, '/result/a') is MISSING
