"""Deterministic applicability extraction from a question: grade, country, city, topic, scope."""
import re

from domain.data import reference_data
from domain.reference import canonical_city

TOPICS = [
    ('meals', r'\b(meals?|dinner|lunch|breakfast|food|per\s*diem)\b'),
    ('fx', r'\b(exchange\s+rate|fx|currency|usd\s+rate|rate\s+for\s+my\s+claim|conversion)\b'),
    ('deadline', r'\b(submit|submission|deadline|how\s+many\s+days|late)\b'),
    ('flight', r'\b(flights?|airfare|fare|one[-\s]way|round\s+trip|business\s+class|premium\s+economy|economy|cabin)\b'),
    ('local_transport', r'\b(taxi|taxis|cab|cabs|ride|rides|airport\s+transfer|local\s+(transport|travel)|metro|bus|train)\b'),
    ('hotel', r'\b(hotel|room|night|nightly|stay|lodging|accommodation)\b'),
    ('evidence', r'\b(receipts?|invoices?|documents?|boarding\s+pass|what\s+do\s+i\s+need)\b'),
]


def topic(message):
    text = message.lower()
    for name, pattern in TOPICS:
        if re.search(pattern, text):
            return name
    return None


def grade(message):
    text = message
    match = re.search(r'\bgrade\s+([EM])\b', text, re.I) or re.search(r'\b(?:an?|the|for)\s+([EM])\b', text) \
        or re.search(r'\b([EM])\s+(?:employee|grade|hotel|one-way|international|domestic|daily|traveler|traveller)\b', text)
    if match:
        return match.group(1).upper()
    if re.search(r'\bmanagers?\b', text, re.I):
        return 'M'
    return None


def location(message):
    """Return (country, city) from known city and country names, else (None, None)."""
    gazetteer = reference_data()['city_gazetteer']
    names = reference_data()['country_names']
    for code in ('IN', 'US', 'UK', 'SG'):
        for city in sorted(gazetteer[code], key=len, reverse=True):
            if re.search(r'\b%s\b' % re.escape(city), message, re.I):
                return code, canonical_city(city)
    for code in ('IN', 'US', 'UK', 'SG'):
        for name in names[code]:
            pattern = r'\b%s\b' % re.escape(name)
            flags = 0 if name.isupper() else re.I
            if re.search(pattern, message, flags):
                return code, None
    return None, None


def scope(message, country):
    text = message.lower()
    if re.search(r'\binternational\b', text):
        return 'international'
    if re.search(r'\bdomestic\b', text) or country == 'IN':
        return 'domestic'
    if country in ('US', 'UK', 'SG'):
        return 'international'
    return None


# Whose rules the question is about. SPARKS policy (the registry and P01-P20) applies only to SPARKS employees; a
# question about Government of India staff or orders is answered from the GoI reference documents in the library.
GOVERNMENT_SCOPE = re.compile(
    r'\b(government\s+of\s+india|goi|central\s+(government|govt\.?)|govt\.?\s+(servants?|employees?|of\s+india)|'
    r'government\s+(servants?|employees?|officers?|officials?)|central\s+civil\s+services|ccs|[67]th\s+cpc|cpc|'
    r'gfr|department\s+of\s+expenditure|dopt|ministry\s+of\s+finance|office\s+memorand(um|a))\b', re.I)


def organization_scope(message):
    """'goi_reference' when the question is about Government of India rules, else None (SPARKS policy)."""
    return 'goi_reference' if GOVERNMENT_SCOPE.search(message or '') else None


def interpret(message):
    country, city = location(message)
    return {'topic': topic(message), 'grade': grade(message), 'country': country, 'city': city,
            'geography': scope(message, country), 'organization_scope': organization_scope(message)}
