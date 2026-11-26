"""Deterministic cap application (P02-P07, P10, P11, P20).

Exclusions come off first. Hotels are capped per night, local transport per
local day and flights per one-way journey. A cap with before_conversion is
compared in its own currency and then converted line by line; a cap with
after_conversion is compared in home currency after documented conversion.
Each converted figure is rounded per line and any residual is reported as a
rounding adjustment, never as a policy violation.
"""
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from domain.errors import DomainIssue
from domain.fx import missing_fx_issue
from domain.money import money_str, round_money, zero
from domain.reference import home_currency, is_known_currency, normalize_country, vocabulary
from domain.registry import RegistryLookupError, parameter, registry_version, resolve_cap

GROUP_BASIS = {'hotel': 'per_night', 'flight': 'per_one_way_journey', 'local_transport': 'per_local_day'}


@dataclass
class Line:
    line_id: str
    category: str
    country: object
    city: object
    currency: object
    amount: object
    excluded: Decimal
    service_date: object
    fx_rate: object = None
    journey_id: object = None
    receipt_id: object = None
    cabin: object = None
    business_purpose: object = True


@dataclass
class LineResult:
    line_id: str
    category: str
    cap_id: object = None
    rule_id: object = None
    claimed_local: object = None
    eligible_local: object = None
    excluded_local: object = None
    over_cap_local: object = None
    claimed_inr: object = None
    eligible_inr: object = None
    excluded_inr: object = None
    over_cap_inr: object = None
    rounding_inr: object = None

    def as_dict(self):
        return {'line_id': self.line_id, 'category': self.category, 'cap_id': self.cap_id,
                'rule_id': self.rule_id, 'registry_version': registry_version(),
                'claimed_inr': money_str(self.claimed_inr), 'eligible_inr': money_str(self.eligible_inr),
                'excluded_inr': money_str(self.excluded_inr), 'over_cap_inr': money_str(self.over_cap_inr),
                'rounding_adjustment_inr': money_str(self.rounding_inr)}


@dataclass
class Calculation:
    lines: list = field(default_factory=list)
    issues: list = field(default_factory=list)
    reasons: list = field(default_factory=list)
    evidence_ids: list = field(default_factory=list)
    over_cap: bool = False
    excluded: bool = False
    compliance_unknown: bool = False
    claimed_known: bool = True

    def add_reason(self, code):
        if code not in self.reasons:
            self.reasons.append(code)

    def add_evidence(self, rule_id):
        if rule_id and rule_id not in self.evidence_ids:
            self.evidence_ids.append(rule_id)

    def total(self, attribute):
        values = [getattr(r, attribute) for r in self.lines]
        if not values or any(v is None for v in values):
            return None
        return sum(values, zero())


def _issue_from_lookup(error):
    readiness = 'HUMAN_REVIEW' if error.reason_code == 'UNSUPPORTED_DESTINATION' else 'NEEDS_CLARIFICATION'
    return DomainIssue(readiness, error.reason_code, error.message, error.missing_fields)


def _validate_line(line, calc):
    """Return False when the line cannot enter any calculation."""
    if line.amount is None:
        calc.issues.append(DomainIssue('NEEDS_CLARIFICATION', 'MISSING_CRITICAL_FIELD',
                                       'The payable amount for %s is unknown.' % line.line_id, ['amount']))
        calc.claimed_known = False
        return False
    if line.amount < zero() or line.excluded < zero() or line.excluded > line.amount:
        calc.issues.append(DomainIssue('INPUT_ERROR', 'INVALID_AMOUNT',
                                       'Amounts must be nonnegative and exclusions cannot exceed the amount.',
                                       ['amount']))
        return False
    if line.currency is None or not is_known_currency(line.currency):
        calc.issues.append(DomainIssue('NEEDS_CLARIFICATION', 'MISSING_CRITICAL_FIELD',
                                       'A supported currency is required for %s.' % line.line_id, ['currency']))
        return False
    if line.service_date is None:
        calc.issues.append(DomainIssue('NEEDS_CLARIFICATION', 'MISSING_CRITICAL_FIELD',
                                       'The service date for %s is unknown.' % line.line_id, ['service_date']))
        return False
    return True


def _policy_exclusions(line, calc):
    """Whole-line exclusions that do not depend on a cap (P04, P05, P08, P10)."""
    if line.category == 'out_of_scope':
        calc.add_reason('OUT_OF_SCOPE_CATEGORY')
        calc.add_evidence('P08')
        return line.amount
    if line.business_purpose is False:
        calc.add_reason('EXCLUDED_ITEM')
        calc.add_evidence('P10')
        return line.amount
    if line.category == 'flight' and line.cabin is not None:
        if str(line.cabin).lower() not in parameter('PARAM-ALLOWED-CABIN'):
            calc.add_reason('CABIN_NOT_PERMITTED')
            calc.add_evidence('P04')
            return line.amount
    return line.excluded


def _group_key(line):
    if line.category == 'hotel':
        return ('hotel', line.line_id)
    if line.category == 'flight':
        return ('flight', line.journey_id or line.line_id)
    if line.category == 'local_transport':
        return ('local_transport', normalize_country(line.country), line.service_date)
    return ('other', line.line_id)


def _sort_key(line):
    return (line.service_date or date.min, str(line.receipt_id or ''), line.line_id)


def _allocate(capacity, allowed_amounts):
    """Allocate a capped amount across lines in stable order (TEST_PROTOCOL section 9)."""
    remaining, eligible = capacity, []
    for allowed in allowed_amounts:
        take = min(allowed, remaining)
        eligible.append(take)
        remaining -= take
    return eligible


def calculate(lines, grade):
    calc = Calculation()
    usable = []
    for line in lines:
        if not _validate_line(line, calc):
            continue
        line.excluded = _policy_exclusions(line, calc)
        if line.excluded > zero():
            calc.excluded = True
            calc.add_reason('EXCLUDED_ITEM')
            calc.add_evidence('P10')
        usable.append(line)
    if calc.issues and not usable:
        calc.compliance_unknown = True
        return calc

    groups = {}
    for line in sorted(usable, key=_sort_key):
        groups.setdefault(_group_key(line), []).append(line)

    for key, members in groups.items():
        results = [LineResult(m.line_id, m.category) for m in members]
        calc.lines.extend(results)
        for member, result in zip(members, results):
            result.claimed_local = member.amount
            result.excluded_local = member.excluded
            rate = member.fx_rate if member.currency != home_currency() else Decimal(1)
            result.claimed_inr = round_money(member.amount * rate) if rate is not None else None
            result.excluded_inr = round_money(member.excluded * rate) if rate is not None else None
            if rate is None:
                calc.issues.append(missing_fx_issue(member.currency, member.service_date))
                calc.add_reason('UNDOCUMENTED_FX')
            elif member.currency != home_currency():
                calc.add_evidence('P11')

        if key[0] == 'other':
            for member, result in zip(members, results):
                result.eligible_local = zero()
                result.over_cap_local = zero()
                if result.claimed_inr is not None:
                    result.eligible_inr = zero()
                    result.over_cap_inr = zero()
                    result.rounding_inr = result.claimed_inr - result.excluded_inr
            continue

        lead = members[0]
        try:
            cap = resolve_cap(lead.category, lead.country, lead.city, grade, lead.service_date)
        except RegistryLookupError as error:
            calc.issues.append(_issue_from_lookup(error))
            calc.add_reason(error.reason_code)
            calc.add_evidence({'hotel': 'P03', 'local_transport': 'P07', 'flight': 'P05'}.get(lead.category))
            calc.compliance_unknown = True
            continue
        calc.add_evidence(cap.rule_id)
        for result in results:
            result.cap_id, result.rule_id = cap.cap_id, cap.rule_id

        if cap.conversion_order == 'before_conversion':
            if any(m.currency != cap.currency for m in members):
                calc.issues.append(DomainIssue('NEEDS_CLARIFICATION', 'CURRENCY_MISMATCH',
                                               'Amounts under %s must be stated in %s or carry a documented '
                                               'common-currency basis.' % (cap.cap_id, cap.currency), ['currency']))
                calc.add_reason('CURRENCY_MISMATCH')
                calc.compliance_unknown = True
                continue
            allowed = [m.amount - m.excluded for m in members]
            eligible = _allocate(min(sum(allowed, zero()), cap.amount), allowed)
            for member, result, allow, elig in zip(members, results, allowed, eligible):
                result.eligible_local, result.over_cap_local = elig, allow - elig
                if result.over_cap_local > zero():
                    calc.over_cap = True
                rate = member.fx_rate if member.currency != home_currency() else Decimal(1)
                if rate is not None:
                    result.eligible_inr = round_money(elig * rate)
                    result.over_cap_inr = round_money((allow - elig) * rate)
                    result.rounding_inr = result.claimed_inr - (
                        result.eligible_inr + result.excluded_inr + result.over_cap_inr)
        else:
            if cap.currency != home_currency() or any(r.claimed_inr is None for r in results):
                calc.compliance_unknown = True
                continue
            allowed = [r.claimed_inr - r.excluded_inr for r in results]
            eligible = _allocate(min(sum(allowed, zero()), cap.amount), allowed)
            for result, allow, elig in zip(results, allowed, eligible):
                result.eligible_inr, result.over_cap_inr = elig, allow - elig
                result.rounding_inr = zero()
                if result.over_cap_inr > zero():
                    calc.over_cap = True
        if calc.over_cap:
            calc.add_reason('OVER_CATEGORY_CAP')
    for issue in calc.issues:
        calc.add_reason(issue.reason_code)
    assert all(code in {r['code'] for r in vocabulary('reason_code')} for code in calc.reasons)
    return calc
