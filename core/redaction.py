"""Redact secrets and personal data before anything is logged or exported (OBS04)."""
import re

_PATTERNS = [
    (re.compile(r'sk-ant-[A-Za-z0-9_\-]{8,}'), '[REDACTED_API_KEY]'),
    (re.compile(r'\b(?:sk|pk|rk)-[A-Za-z0-9]{16,}\b'), '[REDACTED_API_KEY]'),
    (re.compile(r'(?i)bearer\s+[A-Za-z0-9._\-]{8,}'), 'Bearer [REDACTED]'),
    (re.compile(r'\b[0-9]{4}[ -]?[0-9]{4}[ -]?[0-9]{4}[ -]?[0-9]{4}\b'), '[REDACTED_CARD]'),
    (re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}'), '[REDACTED_EMAIL]'),
    (re.compile(r'data:image/[a-z]+;base64,[A-Za-z0-9+/=]+'), '[REDACTED_IMAGE]'),
]


def redact_text(text, secrets=()):
    if not isinstance(text, str):
        return text
    for secret in secrets:
        if secret:
            text = text.replace(secret, '[REDACTED_SECRET]')
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def redact(value, secrets=()):
    if isinstance(value, dict):
        return {k: ('[REDACTED]' if k.lower() in {'authorization', 'api_key', 'token', 'password', 'image_base64'}
                    else redact(v, secrets)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, secrets) for v in value]
    return redact_text(value, secrets)
