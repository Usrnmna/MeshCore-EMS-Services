"""Bounded structured location briefings with whole-item radio reduction."""
from datetime import datetime, timezone
import json
import os
import queue
import sqlite3
import sys
import threading
import time

from . import brief_sources as sources, heat_adv, uv_index, weather_lookup
from .response_text import MESSAGE_BYTES

HELP = '!brief [alerts|weather|fire|water] LOCATION. Default: all four. Selected info, not all-clear; local --json.'
FAILURES = (OSError, ValueError, RuntimeError, TypeError, KeyError, AttributeError, OverflowError, ImportError, sqlite3.Error)


def parse(text):
    """Accept one optional category and the established bounded location grammar."""
    if not isinstance(text, str) or len(text.encode()) > 150 or any(not c.isprintable() for c in text):
        raise ValueError('Invalid brief query; use !brief help.')
    words = text.split()
    if not words or words == ['help']:
        return None
    categories = (words.pop(0),) if words[0] in sources.CATEGORIES else sources.CATEGORIES
    if not words or any(w.lower() in (*sources.CATEGORIES, 'help', 'nan', 'inf', 'infinity') for w in words):
        raise ValueError('Invalid brief selector/location; use !brief help.')
    return categories, uv_index.parse_location(' '.join(words))


def bounded(call, seconds):
    """Wait only for this reader's allowance; abandon late results.

    Workers are request-local daemon threads, not a monitoring service. Each
    reader also has transport/SQLite limits. No executor shutdown waits for a
    slow optional source; late output cannot replace the returned briefing.
    """
    if seconds <= 0:
        raise TimeoutError('Brief execution budget exhausted')
    output = queue.Queue(maxsize=1)

    def run():
        try:
            output.put((True, call()))
        except Exception as exc:
            output.put((False, exc))

    worker = threading.Thread(target=run, daemon=True, name='brief-reader')
    worker.start()
    try:
        success, value = output.get(timeout=seconds)
    except queue.Empty as exc:
        raise TimeoutError('Brief source timed out') from exc
    if not success:
        raise value
    return value


def recheck(results, now):
    """Re-evaluate time-sensitive evidence after other categories finish."""
    for category, outcome in results.items():
        if category == 'alerts' and 'evidence' in outcome:
            expired = any(item['expires'] <= now for item in outcome['items'])
            checked = outcome['checked']
            # Re-run the complete revision set, including future-effective
            # updates/cancellations that were not displayed on initial read.
            outcome.update(sources.alerts_from(outcome['evidence'], now))
            outcome.update(checked=checked, evaluated_at=now)
            if expired:
                outcome['issues'].append('Alert expired during briefing')
        if category == 'fire':
            for status in outcome.get('sources', []):
                fetched = status.get('fetched')
                status.update(stale=fetched is None or now-fetched > status['max_age'],
                              age_seconds=None if fetched is None else max(0, now-fetched))
                if status['stale'] or status.get('error') or fetched > now:
                    outcome['issues'].append('Fire cache coverage stale/failed/incomplete')
        retained = []
        for item in outcome['items']:
            if category == 'alerts' and not item['effective'] <= now < item['expires']:
                outcome['issues'].append('Alert expired during briefing')
                continue
            if category == 'weather':
                data = item['data']
                expired = (weather_lookup.instant(data['end']).timestamp() <= now
                           or not 0 <= now-weather_lookup.instant(data['updated']).timestamp() <= weather_lookup.SOURCE_MAX_AGE
                           or data['delivery'] != 'live' and now >= data['cache_expires'])
                if expired:
                    outcome['issues'].append('Weather expired during briefing')
                    continue
                data['gap_seconds'] = max(0, weather_lookup.instant(data['start']).timestamp()-now)
            if category == 'water':
                from .gauge_lookup import qualify
                # Preserve each installed quality flag and the reader's configured age limit.
                rows = [qualify(r, now, outcome['reading_max_age']) for r in item['readings']]
                item.update(readings=rows, eligible_readings=(sum(r['usable'] for r in rows)
                            if outcome.get('observations_available', True) else None))
            if category == 'fire':
                for detail in item['details'].values():
                    observed, acquired = detail['observed'], detail['acquisition']
                    detail['freshness'] = ('unknown' if observed is None else 'future' if observed > now else
                                           'stale' if now-observed > outcome['stale_after'] else 'recent')
                    detail.update(cache_stale=acquired is None or now-acquired > outcome['stale_after'],
                                  cache_future=acquired is not None and acquired > now)
                    if detail['cache_stale'] or detail['cache_future'] or detail['freshness'] != 'recent':
                        detail['partial'] = True
                        outcome['issues'].append('Fire fields stale/unknown; see !fire')
            retained.append(item)
        outcome['items'] = retained
        if outcome['issues'] and outcome['state'] == 'ok':
            outcome['state'] = 'partial'


def lookup(text, *, clock=time.time, budget=None, readers=None, client_factory=None):
    """Resolve once, collect selected structured categories and retain partial results."""
    query = parse(text)
    if query is None:
        return {'help': True}
    categories, location = query
    budget = budget or sources.Budget()
    readers = sources.READERS if readers is None else readers
    client_factory = client_factory or (lambda: sources.Client(budget, clock))
    resolver_client = client_factory()
    point = bounded(lambda: heat_adv.resolve_location(location, fetch=resolver_client.geocode),
                    min(5, budget.deadline-time.monotonic()))
    results = {}
    for category in categories:
        remaining = budget.deadline-time.monotonic()
        if remaining <= 0:
            results[category] = sources.result('not_checked', issues=['Execution limit; not checked'])
            continue
        if category not in readers:
            results[category] = sources.result('unavailable', issues=['Category prerequisite unavailable'])
            continue
        client = client_factory()
        try:
            outcome = bounded(lambda c=category, transport=client: readers[c](point, transport, clock),
                              min(sources.CATEGORY_SECONDS, remaining))
            if (not isinstance(outcome, dict) or not isinstance(outcome.get('items'), list)
                    or outcome.get('state') not in ('ok', 'partial', 'failed', 'timeout', 'unavailable', 'not_checked')
                    or not isinstance(outcome.get('issues'), list)):
                raise ValueError('Invalid structured source result')
            results[category] = outcome
        except TimeoutError:
            results[category] = sources.result('timeout', issues=['Source timed out'])
        except ImportError:
            results[category] = sources.result('unavailable', issues=['Category dependency unavailable'])
        except sources.LimitReached:
            results[category] = sources.result('not_checked', issues=['Request limit; check incomplete'])
        except Exception:
            # One adapter's unexpected failure must not discard other sources.
            results[category] = sources.result('failed', issues=['Source failed or evidence unavailable/invalid'])
    evaluated_at = clock()
    for category, outcome in list(results.items()):
        try:
            recheck({category: outcome}, evaluated_at)
            # Invalid optional-source metadata must not prevent JSON output or
            # radio formatting of the other, independently usable categories.
            json.dumps(outcome, allow_nan=False)
            for item in outcome['items']:
                if item.get('kind') != ('alert' if category == 'alerts' else category):
                    raise ValueError('Unexpected briefing item kind')
                item_text(item)
        except FAILURES:
            results[category] = sources.result('failed', issues=['Source result invalid during final evaluation'])
    return dict(point=list(point), checked=clock(), selected=list(categories), categories=results,
                not_selected=[c for c in sources.CATEGORIES if c not in categories],
                requests=budget.requests, qualification='Selected information; not a comprehensive check or all-clear.')


def stamp(value):
    """Use explicit UTC dates and minutes in compact briefing evidence."""
    return datetime.fromtimestamp(value, timezone.utc).strftime('%m-%d %H:%MZ')


def item_text(item):
    """Construct complete items from structured evidence, never command replies."""
    kind = item['kind']
    if kind == 'alert':
        return f'NWS {item["event"]} {item["id"]}; sent {stamp(item["sent"])}; until {stamp(item["expires"])}'
    if kind == 'weather':
        data = item['data']
        fields, _ = weather_lookup.fields(data['period'], data['mode'])
        delivery = '' if data['delivery'] == 'live' else data['delivery'] + '; '
        gap = 'future gap; ' if data['gap_seconds'] else ''
        start, end, updated = (weather_lookup.instant(data[k]).timestamp() for k in ('start', 'end', 'updated'))
        # The date is shared only when it is identical in UTC; no host timezone.
        start_text = stamp(start)
        end_text = stamp(end)[6:] if stamp(end)[:5] == start_text[:5] else stamp(end)
        update_text = stamp(updated)[6:] if stamp(updated)[:5] == start_text[:5] else stamp(updated)
        return (f'NWS {delivery}{gap}forecast {start_text}-{end_text}; upd {update_text}; '
                + '; '.join(fields))
    if kind == 'fire':
        return f'Fire {item["id"]}; cached map distance {item["distance_miles"]:.1f}mi; details !fire'
    availability = ('snapshot readings unknown' if item['eligible_readings'] is None else
                    f'{item["eligible_readings"]} eligible snapshot series')
    return f'{item["id"]}: {item["distance_miles"]:.1f}mi; {availability}; live unchecked; not upstream'


def fit(text, fallback='Brief withheld; not all-clear.'):
    """Account for the service sender prefix without slicing fields or UTF-8 bytes."""
    budget = MESSAGE_BYTES-len(('@'+os.environ.get('MESHCORE_SENDER', 'Reader')+' ').encode())
    return next((v for v in (text, fallback, 'Not all-clear.') if len(v.encode()) <= budget), '')


def render(data):
    """Retain alert presence and failures before spending space on secondary detail."""
    if data.get('help'):
        return fit(HELP, '!brief [alerts|weather|fire|water] LOCATION; help')
    outcomes = data['categories']
    alerts = outcomes.get('alerts', {}).get('items', [])
    failures = [c for c, r in outcomes.items() if r['state'] in ('failed', 'timeout', 'unavailable', 'not_checked')]
    limited = [c for c, r in outcomes.items() if r['state'] == 'partial']
    parts = []
    if alerts:
        parts.append(f'NWS: {len(alerts)} applicable alert(s)')
    if failures:
        parts.append('Unavailable: '+','.join(failures))
    if limited:
        labels = {'alerts': 'alerts incomplete', 'weather': 'weather provider failed',
                  'fire': 'fire cache limited', 'water': 'water installed only'}
        if any('expired' in issue.lower() for issue in outcomes.get('weather', {}).get('issues', [])):
            labels['weather'] = 'weather expired'
        if outcomes.get('water', {}).get('observations_available') is False:
            labels['water'] = 'water readings unavailable'
        parts.append('Limited: '+','.join(labels[c] for c in limited))
    # A focused query never implies the other categories were checked.
    parts.append('Selected only; not all-clear')
    items = alerts + [item for c in sources.CATEGORIES if c != 'alerts'
                      for item in outcomes.get(c, {}).get('items', [])]
    if not items and not failures and not limited:
        parts.insert(0, 'No matching records in checked '+','.join(data['selected']))
        parts.insert(1, 'at '+stamp(data['checked']))
    base = '; '.join(parts)
    selected = []
    for index, item in enumerate(items):
        candidate = '; '.join([base] + selected + [item_text(item)])
        if index+1 < len(items):
            candidate += '; more omitted'
        if fit(candidate, '') != candidate:
            break
        selected.append(item_text(item))
    suffix = '; more omitted' if selected and len(selected) < len(items) else ''
    if items and not selected:
        suffix = '; details withheld; local --json'
    text = '; '.join([base]+selected)+suffix
    # With very long sender tags, alert presence or a failed check remains explicit.
    fallback = ('NWS alerts present; briefing incomplete; not all-clear.' if alerts else
                'Brief incomplete; source/detail unavailable; not all-clear.')
    return fit(text, fallback)


def main(argv=None):
    """Run directly or via the service; structured output is strictly local-only."""
    args = list(sys.argv[1:] if argv is None else argv)
    structured = bool(args and args[0] == '--json')
    if structured:
        args.pop(0)
    service = bool(os.environ.get('MESHCORE_REQUEST_ID') or os.environ.get('MESHCORE_SENDER'))
    try:
        if structured and service:
            raise ValueError('Brief structured output is local-only.')
        data = lookup(' '.join(args))
        print(json.dumps(data, ensure_ascii=True, allow_nan=False) if structured else render(data))
    except FAILURES:
        message = ('Brief structured output is local-only.' if structured and service else
                   'Brief unavailable or query invalid; use !brief help. Not all-clear.')
        print(json.dumps({'error': message}) if structured and not service else fit(message))
    return 0
