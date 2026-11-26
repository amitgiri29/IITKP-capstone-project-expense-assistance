"""Deterministic guards that run before any model call (P18, FR09)."""
import re

_SECRET = re.compile(r'\b(api[\s_-]?keys?|secret|access[\s_-]?token|tokens?|passwords?|credentials?|private[\s_-]?keys?|'
                     r'env(?:ironment)?\s+var(?:iable)?s?|\.env)\b', re.I)
_HIDDEN = re.compile(r'\b(system|hidden|developer|internal)\s+(prompt|instructions?|message|rules)\b|'
                     r'\b(ignore|disregard)\s+(all\s+|your\s+|previous\s+)*(instructions|rules)\b', re.I)
_OTHERS = re.compile(r'\b(other|another|someone\s+else\'?s?|all)\s+(employees?|users?|travell?ers?|people|persons?)\b'
                     r'.{0,40}\b(receipts?|claims?|expenses?|data|records?|trips?)\b', re.I)
_BOOKING = re.compile(r'\b(can|could|would|will)\s+you\s+(please\s+)?(book|reserve|purchase|buy|pay(\s+for)?|cancel|modify|change)\b'
                      r'|\bplease\s+(book|reserve|purchase|buy|pay|cancel)\b'
                      r'|^\s*(book|reserve|purchase|buy|cancel)\b'
                      r'|\b(book|reserve|purchase|buy)\s+(me|us|it|this|that|one)\b'
                      r'|\b(book|reserve|purchase|buy)\b.{0,40}\bfor\s+(me|us)\b'
                      r'|\bmake\s+(a|the)\s+(booking|reservation)\b', re.I)

DECLINE_SECRETS = ('I can\'t share credentials, configuration values or hidden instructions. I can help with travel '
                   'policy questions, receipt reviews and flight or hotel search.')
DECLINE_OTHERS = ('I can only show records from your own authorized session. I can help with your own receipts, '
                  'claims and travel policy questions.')
DECLINE_BOOKING = ('I can\'t book, reserve, pay for, cancel or change travel. I can search flights and hotels and show '
                   'policy-compliant options for you to book through your company\'s booking channel.')


def screen(message):
    """Return a refusal dict for a request that must never reach the model, else None."""
    text = message or ''
    if _SECRET.search(text) or _HIDDEN.search(text):
        return {'refused': True, 'category': 'secret_request', 'action': 'Declined and redirected to expense tasks.',
                'answer': DECLINE_SECRETS, 'reasons': [], 'evidence_ids': ['P18']}
    if _OTHERS.search(text):
        return {'refused': True, 'category': 'cross_session', 'action': 'Declined; only the caller\'s own records.',
                'answer': DECLINE_OTHERS, 'reasons': [], 'evidence_ids': ['P18']}
    if _BOOKING.search(text):
        return {'refused': True, 'category': 'booking', 'action': 'Declined booking and offered search instead.',
                'answer': DECLINE_BOOKING, 'reasons': [], 'evidence_ids': ['P18']}
    return None
