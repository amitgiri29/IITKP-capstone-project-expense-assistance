"""Submission deadline (P13)."""
from domain.inputs import parse_date
from domain.registry import parameter


def deadline_outcome(trip_end, submitted_on):
    end, submitted = parse_date(trip_end), parse_date(submitted_on)
    if end is None or submitted is None:
        return {'late': None, 'days_after_trip_end': None, 'readiness': 'NEEDS_CLARIFICATION',
                'reason': 'INCONSISTENT_DATES',
                'missing_fields': [k for k, v in (('trip_end', end), ('submitted_on', submitted)) if v is None]}
    elapsed = (submitted - end).days
    if elapsed < 0:
        return {'late': None, 'days_after_trip_end': elapsed, 'readiness': 'NEEDS_CLARIFICATION',
                'reason': 'INCONSISTENT_DATES', 'missing_fields': ['submitted_on']}
    late = elapsed > parameter('PARAM-SUBMISSION-DEADLINE-DAYS')
    return {'late': late, 'days_after_trip_end': elapsed,
            'readiness': 'HUMAN_REVIEW' if late else 'READY_FOR_REVIEW',
            'reason': 'LATE_SUBMISSION' if late else None, 'missing_fields': []}


def validate_submission_deadline(payload):
    """Entrypoint validate_submission_deadline (GT106, GT107). Tests the deadline rule only."""
    outcome = deadline_outcome(payload.get('trip_end'), payload.get('submitted_on'))
    outcome['reasons'] = [outcome.pop('reason')] if outcome.get('reason') else []
    outcome['evidence_ids'] = ['P13']
    outcome['message'] = ('Submitted %s days after the trip ended.' % outcome['days_after_trip_end']
                          if outcome['days_after_trip_end'] is not None else 'Trip end and submission dates are required.')
    return outcome
