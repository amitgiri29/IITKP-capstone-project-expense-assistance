"""Structured domain issues.

An issue carries the readiness it forces, a reason code from the reference
vocabulary and, where relevant, the missing-field codes to ask for.
"""
from domain.reference import require_reason


class DomainIssue(Exception):
    def __init__(self, readiness, reason_code, message, missing_fields=(), ask_for=()):
        super().__init__(message)
        self.readiness = readiness
        self.reason_code = require_reason(reason_code)
        self.message = message
        self.missing_fields = list(missing_fields)
        self.ask_for = list(ask_for)

    def as_dict(self):
        return {'readiness': self.readiness, 'reason': self.reason_code, 'message': self.message,
                'missing_fields': self.missing_fields, 'ask_for': self.ask_for}
