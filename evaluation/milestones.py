"""Which evaluation entrypoints each milestone makes runnable."""
MILESTONE_ENTRYPOINTS = {
    'M1': ['aggregate_local_transport', 'assess_confirmed_claim', 'calculate_budget', 'convert_currency_lines',
           'detect_duplicates', 'resolve_fx', 'resolve_policy_conflict', 'validate_amount',
           'validate_claim_context', 'validate_submission_deadline'],
    'M2': ['validate_upload', 'authorize_session', 'handle_secret_request'],
    'M3': ['answer_policy_question', 'validate_and_repair_citations'],
    'M4': ['parse_image_then_review', 'check_image_capability', 'correct_claim', 'resume_conversation'],
    'M5': ['search_and_assess_offers'],
    'M6': ['parse_planner_output'],
}


def entrypoints_through(milestone):
    order = list(MILESTONE_ENTRYPOINTS)
    selected = []
    for name in order[:order.index(milestone) + 1]:
        selected.extend(MILESTONE_ENTRYPOINTS[name])
    return selected
