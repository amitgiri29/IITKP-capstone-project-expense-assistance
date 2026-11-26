"""Trip budget comparison, independent of policy compliance (P12)."""
from domain.money import money_str, to_decimal
from domain.registry import parameter


def budget_outcome(claimed_total_inr, budget_inr, coverage_complete):
    claimed = to_decimal(claimed_total_inr)
    budget = to_decimal(budget_inr)
    outcome = {'budget_status': 'UNKNOWN', 'remaining_budget_inr': None, 'budget_excess_inr': None,
               'display_label': 'claimed total', 'action': None, 'missing_fields': []}
    if coverage_complete is False:
        outcome['display_label'] = 'submitted subtotal'
        outcome['action'] = ('Show the submitted subtotal; the trip budget comparison stays unknown until '
                             'every trip expense is submitted.')
        return outcome
    if budget is None:
        outcome['action'] = 'Ask for an INR trip budget if the traveler wants a budget comparison.'
        outcome['missing_fields'] = ['budget_inr']
        return outcome
    if claimed is None:
        return outcome
    within = claimed <= budget if parameter('PARAM-BUDGET-EQUALITY-WITHIN') else claimed < budget
    outcome['budget_status'] = 'WITHIN_BUDGET' if within else 'OVER_BUDGET'
    if within:
        outcome['remaining_budget_inr'] = money_str(budget - claimed)
    else:
        outcome['budget_excess_inr'] = money_str(claimed - budget)
    return outcome


def calculate_budget(payload):
    """Entrypoint calculate_budget (GT102, GT103)."""
    result = budget_outcome(payload.get('confirmed_total_inr', payload.get('claimed_total_inr')),
                            payload.get('budget_inr'), payload.get('coverage_complete', True))
    result['message'] = result['action'] or 'Budget status: %s.' % result['budget_status']
    return result
