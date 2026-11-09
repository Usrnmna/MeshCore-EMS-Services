"""Stateless geographic identification with whole-field radio replies."""
import json
import math
import os
import re
import sys
import time

from . import where_data as data
from .response_text import MESSAGE_BYTES

HELP = '!where LAT LON [park|basin|firezone]; basin [Region|Unit|Area|Subarea|SPW|PW]. Map containment only.'
QUALIFICATION = 'Map reference only; no legal access, safety, hazards or hydrologic connectivity established.'


def parse(text):
    """Accept one coordinate pair and at most one category and CalWater level."""
    if not isinstance(text, str) or len(text.encode('utf-8')) > 150 or any(not c.isprintable() for c in text):
        raise ValueError('Invalid query')
    words = text.split()
    if words in ([], ['help']):
        return None
    if len(words) not in (2, 3, 4):
        raise ValueError('Invalid query')
    if any(not re.fullmatch(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?', word)
           for word in words[:2]):
        raise ValueError('Invalid coordinates')
    lat, lon = map(float, words[:2])
    if not math.isfinite(lat) or not math.isfinite(lon) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise ValueError('Invalid coordinates')
    category = words[2] if len(words) > 2 else None
    level = words[3] if len(words) > 3 else None
    if ((category is not None and category not in data.SOURCES)
            or (level is not None and (category != 'basin' or level not in data.basin.LEVELS))):
        raise ValueError('Invalid selector')
    return lat, lon, category, level


def lookup(text):
    """Keep independently usable collections; reject changed sources before output."""
    query = parse(text)
    if query is None:
        return {'help': True}
    from shapely.geometry import Point
    lat, lon, category, level = query
    point = Point(lon, lat)
    result = dict(latitude=lat, longitude=lon, selector=category, level=level,
                  qualification=QUALIFICATION, sources=[])
    deadline = time.monotonic() + data.QUERY_SECONDS
    checks = []
    for group in (category,) if category else data.SOURCES:
        for source, reader in data.SOURCES[group]:
            entry = dict(category=group, source=source, status='unavailable', matches=[])
            result['sources'].append(entry)
            try:
                data.tick(deadline)
                rows, verify, metadata = reader(point, deadline, level)
                entry.update(metadata, status='matches' if rows else 'no_match',
                             matches=rows[:data.MAX_MATCHES], partial=len(rows) > data.MAX_MATCHES,
                             match_count=len(rows))
                # Absence in a thematic layer does not prove a point is outside
                # its documented coverage. NWS selection defines an actual union.
                if not rows and source == 'nws':
                    entry['status'] = 'outside_coverage'
                checks.append((entry, verify))
            except data.FAILURES as exc:
                entry['reason'] = failure_reason(exc)
    for entry, verify in checks:
        try:
            verify()
        except data.FAILURES as exc:
            entry.update(status='unavailable', matches=[], reason=failure_reason(exc))
            entry.pop('match_count', None)
    result['partial'] = any(e['status'] == 'unavailable' or e.get('partial') for e in result['sources'])
    return result


def failure_reason(error):
    """Expose useful failure classes without transmitting local paths or exceptions."""
    message = str(error).casefold()
    if isinstance(error, FileNotFoundError):
        return 'Missing or explicitly removed collection'
    if isinstance(error, ImportError):
        return 'Runtime dependency unavailable'
    if any(word in message for word in ('integrity', 'checksum')):
        return 'Integrity failure'
    if any(word in message for word in ('incompatible', 'generation', 'changed')):
        return 'Incompatible or changed generation'
    if any(word in message for word in ('limit', 'bound')):
        return 'Query limit exceeded; narrow selection'
    if 'disabled' in message:
        return 'Collection feature disabled'
    return 'Invalid or unsupported collection'


def fit(text, fallback='Result withheld; use local --json.'):
    """Withhold oversized qualified text rather than truncating identifiers."""
    budget = MESSAGE_BYTES - len(('@' + os.environ.get('MESHCORE_SENDER', 'Reader') + ' ').encode('utf-8'))
    for candidate in (text, fallback, 'Withheld.'):
        if len(candidate.encode('utf-8')) <= budget:
            return candidate
    return ''


def render(result):
    """Prefer complete identities; explicitly withhold details that cannot fit."""
    if result.get('help'):
        return fit(HELP, '!where LAT LON [park|basin|firezone]; local --json for full results.')
    parts = []
    for entry in result['sources']:
        label = entry['source']
        status = entry['status']
        if status != 'matches':
            parts.append(label + ':' + {'no_match': 'no match', 'unavailable': 'unavailable',
                                       'outside_coverage': 'outside coverage'}[status])
        else:
            rows = [r['id'] + '(' + (r.get('level', '') + ':' if r.get('level') else '') + r['relation']
                    + (',repaired' if r['repaired'] else '') + ')' for r in entry['matches']]
            parts.append(label + ':' + ','.join(rows) + ('; partial' if entry.get('partial') else ''))
    caveat = 'Mapped coverage only; no access/safety/connectivity.'
    if any(e['category'] == 'firezone' for e in result['sources']):
        caveat += ' Not evacuation zones.'
    text = '; '.join(parts) + '. ' + caveat
    if result['partial']:
        text = 'Partial; ' + text
    if fit(text, ''):
        return text
    # A count is explicitly a withheld set, never an arbitrarily selected match.
    labels = {'stateparks': 'Parks', 'ebmud': 'EBMUD', 'calwater': 'CalWater', 'nws': 'NWS'}
    summary = '; '.join(labels[e['source']] + ':' + (str(e['match_count']) if e['status'] == 'matches'
                         else e['status'].replace('_', ' ')) for e in result['sources'])
    if result['partial']:
        summary = 'Partial; ' + summary
    fallback = ('Partial; ' if result['partial'] else '') + 'Details withheld; use selector/local --json.'
    return fit(summary + '; map matches. Details withheld; use selector/local --json.',
               fallback)


def main(argv=None):
    """Run the dedicated CLI; structured output is prohibited in service context."""
    args = list(sys.argv[1:] if argv is None else argv)
    structured = bool(args and args[0] == '--json')
    if structured:
        args.pop(0)
    try:
        if structured and (os.environ.get('MESHCORE_REQUEST_ID') or os.environ.get('MESHCORE_SENDER')):
            raise ValueError('Structured output is local only')
        result = lookup(' '.join(args))
        print(json.dumps(result, ensure_ascii=True) if structured else render(result))
    except data.FAILURES:
        print(fit('Geographic query/dependency unavailable or invalid; use !where help.'))
    return 0
