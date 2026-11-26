"""The documented error envelope (AC20). Codes and statuses come from reference_data.json."""
from domain.data import reference_data


def status_for(code):
    for entry in reference_data()['vocabularies']['error_code']:
        if entry['code'] == code:
            return entry['http_status']
    raise KeyError(code)


class ApiError(Exception):
    def __init__(self, code, message, field=None, retry_after_seconds=None):
        super().__init__(message)
        self.code = code
        self.status = status_for(code)
        self.message = message
        self.field = field
        self.retry_after_seconds = retry_after_seconds


def envelope(code, message, request_id, field=None, retry_after_seconds=None):
    return {'error_code': code, 'message': message, 'field': field, 'request_id': request_id,
            'retry_after_seconds': retry_after_seconds}
