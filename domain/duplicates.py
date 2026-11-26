"""Duplicate detection (P14). Flags and holds; never accuses or double counts."""
from domain.money import money_str, to_decimal, zero
from domain.reference import home_currency


def detect_duplicates(payload):
    """Entrypoint detect_duplicates (GT105)."""
    receipts = payload.get('receipts') or []
    seen, potential, suspected = {}, [], []
    loose = {}
    for index, receipt in enumerate(receipts):
        issuer = receipt.get('issuer') or receipt.get('merchant')
        number = receipt.get('id') or receipt.get('receipt_id')
        when = receipt.get('date') or receipt.get('transaction_date')
        amount = receipt.get('amount')
        if issuer and number and when:
            key = (str(issuer).casefold(), str(number), str(when))
            if key in seen:
                potential.append([seen[key], index])
            else:
                seen[key] = index
        elif issuer and when and amount is not None:
            key = (str(issuer).casefold(), str(when), str(to_decimal(amount)))
            if key in loose:
                suspected.append([loose[key], index])
            else:
                loose[key] = index
    held = bool(potential)
    total = None
    if not held and receipts and all((r.get('currency') or home_currency()) == home_currency() for r in receipts):
        total = money_str(sum((to_decimal(r.get('amount')) for r in receipts), zero()))
    reasons = (['POTENTIAL_DUPLICATE'] if potential else []) + (['SUSPECTED_DUPLICATE'] if suspected else [])
    return {'potential_duplicate': held, 'suspected_duplicate': bool(suspected),
            'duplicate_pairs': potential, 'suspected_pairs': suspected,
            'readiness': 'NEEDS_CLARIFICATION' if held else 'READY_FOR_REVIEW',
            'final_total_inr': total, 'claimed_total_inr': total, 'reasons': reasons, 'evidence_ids': ['P14'],
            'message': ('A repeated issuer, receipt number and date is held for confirmation and is not '
                        'counted twice. This is a completeness check, not a fraud finding.') if held else
                       'No repeated receipt was found.'}
