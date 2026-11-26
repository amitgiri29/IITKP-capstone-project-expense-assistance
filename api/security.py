"""Bearer-token sessions and session/organization authorization (AC13, P18)."""
from api.errors import ApiError


def bearer_token(request):
    header = request.headers.get('authorization') or ''
    scheme, _, token = header.partition(' ')
    return token.strip() if scheme.lower() == 'bearer' and token.strip() else None


def session_from_request(request, context):
    token = bearer_token(request)
    if not token:
        raise ApiError('UNAUTHENTICATED', 'A bearer session token is required.')
    session = context.store.session_for_token(token)
    if session is None:
        raise ApiError('UNAUTHENTICATED', 'The session token is not recognized.')
    if session['expires_at'] <= context.clock().isoformat(timespec='seconds'):
        raise ApiError('UNAUTHENTICATED', 'The session has expired. Start a new session.')
    if session['organization_id'] != context.organization['id']:
        raise ApiError('FORBIDDEN_SESSION', 'The session belongs to another organization.')
    return session


def require_admin(session):
    if session.get('role') != 'admin':
        raise ApiError('FORBIDDEN_ROLE', 'Only an administrator can manage the policy library.')


def ensure_owner(session, session_id):
    if session['session_id'] != session_id:
        raise ApiError('FORBIDDEN_SESSION', 'That session is outside your authorized scope.')


def authorize_session(payload, context):
    """Entrypoint authorize_session (GT113): session A asks for session B's records over the real API."""
    from api.main import local_client
    active, requested = payload.get('active_session'), payload.get('requested_session')
    traveler = next(iter(context.travelers))
    now = context.clock()
    token, _ = context.store.create_session(context.organization['id'], traveler,
                                            context.travelers[traveler]['grade'], now,
                                            context.settings.session_ttl_hours, session_id=active)
    with local_client(context) as client:
        response = client.get('/sessions/%s' % requested, headers={'Authorization': 'Bearer ' + token})
    body = response.json()
    denied = response.status_code in (401, 403, 404)
    return {'access': 'DENIED' if denied else 'GRANTED', 'http_status': response.status_code,
            'error_code': body.get('error_code'), 'message': body.get('message', ''), 'evidence_ids': ['P18']}
