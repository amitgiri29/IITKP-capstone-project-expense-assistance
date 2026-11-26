"""Pure helpers for the Claims and Receipts pages (no Streamlit, no HTTP), so they can be unit-tested.

- receipt_to_claim_lines: a confirmed receipt becomes editable lines for the Claims grid
  (one line per hotel night, one per flight journey, one per local-transport charge).
- claim_check_csv / claim_check_html: downloadable copies of a claim check. They only format numbers
  the API already calculated; nothing is recalculated here.
"""
import csv
import html
import io
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal('0.01')
DISCLAIMER = 'An assessment for review, not an approval. Caps come from the reviewed rule registry.'


def _decimal(value):
    return Decimal(str(value)) if value not in (None, '') else None


def receipt_to_claim_lines(fields, claim=None):
    """Claim lines from confirmed receipt fields. Returns [] when there is no amount to claim.

    Hotel: one line per night. Each night's amount from nightly_amounts when there is one per night (personal extras
    are then added to the first night and excluded there); otherwise the payable total split evenly, with the extras
    already inside it and excluded on the first night. Totals always equal what the receipt says.
    """
    claim = claim or {}
    category = fields.get('category') or 'hotel'
    total = _decimal(fields.get('payable_total'))
    try:
        start = date.fromisoformat(str(fields.get('service_date') or fields.get('checkin')))
    except ValueError:
        return []
    extras = sum((_decimal(i.get('amount')) or Decimal(0) for i in fields.get('excluded_items') or []), Decimal(0))
    base = {'category': category, 'country': fields.get('country') or 'IN', 'city': fields.get('city') or '',
            'currency': fields.get('currency') or 'INR', 'fx_rate': claim.get('fx_rate'), 'journey_id': '',
            'cabin': '', 'business_purpose': True, 'receipt_id': fields.get('receipt_id') or ''}
    if category == 'hotel':
        nights = max(1, int(fields.get('nights') or 1))
        nightly = [_decimal(n) for n in fields.get('nightly_amounts') or [] if _decimal(n) is not None]
        if len(nightly) == nights:
            amounts, extras_inside = nightly, False
        elif total is not None:
            share = (total / nights).quantize(CENT, ROUND_HALF_UP)
            amounts, extras_inside = [share] * (nights - 1) + [total - share * (nights - 1)], True
        else:
            return []
        lines = []
        for index, amount in enumerate(amounts):
            first = index == 0
            if first and not extras_inside:
                amount += extras
            lines.append(base | {'amount': float(amount), 'excluded_amount': float(extras if first else 0),
                                 'service_date': start + timedelta(days=index)})
        return lines
    if total is None:
        return []
    line = base | {'amount': float(total), 'excluded_amount': float(extras), 'service_date': start}
    if category == 'flight':
        line['journey_id'] = fields.get('receipt_id') or 'J-%s' % start.isoformat()
    return [line]


def _money(value):
    return '' if value in (None, '') else '%s' % value


def _line_rows(result, inputs):
    for index, line in enumerate(result.get('lines') or []):
        source = inputs[index] if index < len(inputs) else {}
        yield {'#': index + 1, 'category': line['category'].replace('_', ' '),
               'place': source.get('city') or source.get('country') or '',
               'service_date': str(source.get('service_date') or ''), 'currency': source.get('currency') or '',
               'amount': _money(source.get('amount')), 'claimed_inr': _money(line.get('claimed_inr')),
               'eligible_inr': _money(line.get('eligible_inr')), 'over_cap_inr': _money(line.get('over_cap_inr')),
               'excluded_inr': _money(line.get('excluded_inr')), 'rule': line.get('rule_id') or '',
               'cap_id': line.get('cap_id') or 'no cap'}


TOTALS = [('Claimed (INR)', 'claimed_total_inr'), ('Policy-eligible (INR)', 'eligible_total_inr'),
          ('Over category caps (INR)', 'over_cap_total_inr'), ('Excluded (INR)', 'excluded_total_inr'),
          ('Rounding adjustment (INR)', 'rounding_adjustment_inr'), ('Remaining trip budget (INR)', 'remaining_budget_inr'),
          ('Over trip budget (INR)', 'budget_excess_inr')]
STATUSES = [('Readiness', 'readiness'), ('Compliance', 'compliance_status'), ('Budget', 'budget_status')]


def claim_check_csv(assessment, inputs, grade, trip):
    """CSV (UTF-8 with BOM so Excel opens it cleanly): header, one row per line, totals, statuses, issues."""
    result = assessment['assessment']
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(['SPARKS AI Lab claim check', assessment.get('assessment_id', '')])
    writer.writerow(['Grade', grade, 'Trip', trip[0], trip[1], 'Registry', (result.get('registry') or {}).get('version', '')])
    writer.writerow([])
    rows = list(_line_rows(result, inputs))
    header = ['#', 'category', 'place', 'service_date', 'currency', 'amount', 'claimed_inr', 'eligible_inr',
              'over_cap_inr', 'excluded_inr', 'rule', 'cap_id']
    writer.writerow(header)
    for row in rows:
        writer.writerow([row[k] for k in header])
    writer.writerow([])
    for label, key in TOTALS:
        writer.writerow([label, _money(result.get(key)) or '-'])
    for label, key in STATUSES:
        writer.writerow([label, result.get(key) or ''])
    for issue in result.get('issues') or []:
        writer.writerow(['Issue', issue.get('reason', ''), issue.get('readiness', ''), issue.get('message', '')])
    writer.writerow([])
    writer.writerow([DISCLAIMER])
    return ('﻿' + out.getvalue()).encode('utf-8')


def claim_check_html(assessment, inputs, grade, trip, traveler_name, evidence=()):
    """A self-contained printable page (open it and use the browser's Print > Save as PDF)."""
    result, e = assessment['assessment'], html.escape
    rows = ''.join('<tr>%s</tr>' % ''.join('<td%s>%s</td>' % (' class="n"' if k in (
        'amount', 'claimed_inr', 'eligible_inr', 'over_cap_inr', 'excluded_inr') else '', e(str(v)))
        for k, v in row.items()) for row in _line_rows(result, inputs))
    totals = ''.join('<tr><th>%s</th><td class="n">%s</td></tr>' % (e(label), e(_money(result.get(key)) or '-'))
                     for label, key in TOTALS)
    statuses = ''.join('<span class="b">%s: %s</span>' % (e(label), e((result.get(key) or '').replace('_', ' ').lower()))
                       for label, key in STATUSES)
    issues = ''.join('<li><b>%s</b> (%s): %s</li>' % (e(i.get('reason', '').replace('_', ' ').lower()),
                                                    e(i.get('readiness', '').replace('_', ' ').lower()),
                                                    e(i.get('message', ''))) for i in result.get('issues') or [])
    sources = ''.join('<li><b>%s</b> %s</li>' % (e(s.get('rule_id', '')), e(s.get('section', ''))) for s in evidence)
    return ('<!doctype html><html><head><meta charset="utf-8"><title>Claim check %s</title><style>'
            'body{font-family:system-ui,Segoe UI,Arial,sans-serif;color:#0f172a;margin:32px;max-width:960px}'
            'h1{font-size:20px;margin:0 0 4px}p.m{color:#475569;margin:0 0 16px}table{border-collapse:collapse;width:100%%;'
            'margin:12px 0;font-size:13px}th,td{border-bottom:1px solid #e2e8f0;padding:6px 8px;text-align:left}'
            'td.n{text-align:right;font-variant-numeric:tabular-nums}.b{display:inline-block;border:1px solid #cbd5e1;'
            'border-radius:12px;padding:2px 10px;margin:0 6px 6px 0;font-size:12px}.d{color:#64748b;font-size:12px}'
            '</style></head><body><h1>SPARKS AI Lab claim check</h1><p class="m">%s &middot; grade %s &middot; trip %s to %s'
            ' &middot; registry %s &middot; %s</p><div>%s</div><table><thead><tr><th>#</th><th>Category</th><th>Place</th>'
            '<th>Service date</th><th>Currency</th><th>Amount</th><th>Claimed INR</th><th>Eligible INR</th>'
            '<th>Over cap INR</th><th>Excluded INR</th><th>Rule</th><th>Cap</th></tr></thead><tbody>%s</tbody></table>'
            '<table style="width:auto">%s</table>%s%s<p class="d">%s</p></body></html>') % (
        e(assessment.get('assessment_id', '')), e(traveler_name), e(grade), e(str(trip[0])), e(str(trip[1])),
        e((result.get('registry') or {}).get('version', '')), e(assessment.get('assessment_id', '')), statuses, rows,
        totals, '<h3>Issues</h3><ul>%s</ul>' % issues if issues else '',
        '<h3>Policy sources</h3><ul>%s</ul>' % sources if sources else '', e(DISCLAIMER))
