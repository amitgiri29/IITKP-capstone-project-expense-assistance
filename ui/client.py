"""HTTP client for the Streamlit UI. The UI holds no business logic and no provider secrets."""
import os

import httpx

from core.settings import load_settings


class ApiFailure(Exception):
    def __init__(self, status, body):
        super().__init__(body.get('message', 'Request failed'))
        self.status, self.body = status, body


def base_url():
    return os.environ.get('EXPENSE_API_BASE_URL') or load_settings().api_base_url


def call(method, path, token=None, **kwargs):
    headers = {'Authorization': 'Bearer ' + token} if token else {}
    try:
        response = httpx.request(method, base_url().rstrip('/') + path, headers=headers, timeout=120, **kwargs)
    except httpx.HTTPError as exc:
        raise ApiFailure(0, {'error_code': 'API_UNREACHABLE', 'message': 'Cannot reach the API at %s (%s).'
                                                                          % (base_url(), type(exc).__name__)})
    if response.status_code == 204:
        return {}
    body = response.json() if response.content else {}
    if response.status_code >= 400:
        raise ApiFailure(response.status_code, body)
    return body
