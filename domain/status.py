"""Readiness precedence and compliance derivation (P20, SPECIFICATION status table)."""
from domain.reference import readiness_precedence


def highest_readiness(values):
    """Pick the highest-precedence readiness; READY_FOR_REVIEW when nothing blocks."""
    order = readiness_precedence()
    present = [v for v in values if v]
    if not present:
        return order[-1]
    return min(present, key=order.index)


def compliance_status(over_cap, excluded, unknown=False):
    if unknown:
        return 'UNKNOWN'
    if over_cap and excluded:
        return 'MIXED'
    if over_cap:
        return 'EXCEEDS_POLICY'
    if excluded:
        return 'HAS_EXCLUSIONS'
    return 'WITHIN_POLICY'
