"""Structured briefing readers; existing caches remain owned by their services."""
import math
import threading
import time

from . import heat_adv, weather_lookup, weather_source

TOTAL_SECONDS = 35
CATEGORY_SECONDS = 8
MAX_REQUESTS = 8
MAX_ALERTS = 100
MAX_LOCAL_RECORDS = 20000
MAX_SERIES = 32
CATEGORIES = ('alerts', 'weather', 'fire', 'water')


class LimitReached(weather_source.Unavailable):
    """The shared briefing budget prevented a complete source check."""


class Budget:
    """Share a deadline and attempt count, including retries, across all readers."""

    def __init__(self, monotonic=time.monotonic):
        self.monotonic = monotonic
        self.deadline = monotonic() + TOTAL_SECONDS
        self.requests = 0
        self.lock = threading.Lock()

    def reserve(self):
        with self.lock:
            if self.monotonic() >= self.deadline or self.requests >= MAX_REQUESTS:
                raise LimitReached('Brief request budget exhausted.')
            self.requests += 1


class Client(weather_source.Client):
    """Reuse bounded NWS transport with a shared budget and point-alert endpoint."""
    request_seconds = 3

    def __init__(self, budget, clock=time.time, opener=None):
        super().__init__(clock, opener)
        self.budget = budget
        self.deadline = min(budget.deadline, time.monotonic() + CATEGORY_SECONDS)

    @staticmethod
    def allowed_url(url):
        return weather_source.allowed_url(url) or url == weather_source.NWS + '/alerts/active'

    def reserve(self):
        if self.requests >= weather_source.MAX_REQUESTS:
            raise LimitReached('Brief category request limit reached.')
        self.budget.reserve()
        super().reserve()


def result(state='ok', items=None, issues=None, **metadata):
    """Keep availability and coverage separate from an empty successful result."""
    return dict(state=state, items=items or [], issues=issues or [], **metadata)


def alert_id(value):
    """Normalize only the NWS URL wrapper; retain the source CAP identifier."""
    if not isinstance(value, str) or not value or len(value) > 512 or not value.isprintable():
        raise ValueError('Invalid alert identity')
    return value.removeprefix(weather_source.NWS + '/alerts/')


def alerts_from(data, now):
    """Select actual point-matched CAP revisions without title-based merging.

    Referenced updates/cancellations suppress older records even when the new
    revision has expired. Conflicting identities or reference cycles are withheld.
    The caller must supply the authoritative NWS point-filtered response.
    """
    if (not isinstance(data, dict) or data.get('type') != 'FeatureCollection'
            or not isinstance(data.get('features'), list) or len(data['features']) > MAX_ALERTS):
        raise ValueError('Invalid or excessive alert collection')
    issues = ['NWS alert coverage incomplete'] if data.get('pagination', {}).get('next') else []
    records, conflicts = {}, set()
    for feature in data['features']:
        key, p = None, {}
        try:
            p = feature['properties']
            if p.get('status') in ('Exercise', 'System', 'Test', 'Draft'):
                continue
            key = alert_id(p.get('id') or feature.get('id'))
            sent, effective, expires = [weather_lookup.instant(p.get(k)).timestamp()
                                        for k in ('sent', 'effective', 'expires')]
            ends = weather_lookup.instant(p['ends']).timestamp() if p.get('ends') else expires
            event, sender = p.get('event'), p.get('sender')
            if (p.get('status') != 'Actual' or p.get('messageType') not in ('Alert', 'Update', 'Cancel')
                    or not isinstance(sender, str) or not sender or not isinstance(event, str)
                    or not event or not event.isprintable() or len(event) > 200
                    or sent > now or expires <= effective):
                raise ValueError('Invalid alert evidence')
            references = p.get('references') or []
            if not isinstance(references, list) or len(references) > MAX_ALERTS:
                raise ValueError('Invalid alert references')
            refs = []
            for ref in references:
                refid = alert_id(ref['identifier'])
                refsent = weather_lookup.instant(ref['sent']).timestamp()
                refsender = ref.get('sender')
                if refsent >= sent or not isinstance(refsender, str) or not refsender:
                    raise ValueError('Conflicting alert references')
                refs.append((refid, refsent, refsender))
            record = dict(id=key, event=event, sender=sender, sent=sent, effective=effective,
                          expires=min(expires, ends), message_type=p['messageType'], references=refs,
                          properties=p)
            if key in records and records[key] != record:
                conflicts.add(key)
            else:
                records[key] = record
        except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
            issues.append('NWS alert evidence invalid; coverage incomplete')
            if key is not None:
                conflicts.add(key)
            # Malformed revisions cannot leave their referenced old warning
            # looking authoritative. Preserve unrelated eligible alerts.
            if isinstance(p, dict) and isinstance(p.get('references'), list):
                for ref in p['references'][:MAX_ALERTS]:
                    try:
                        conflicts.add(alert_id(ref['identifier']))
                    except (ValueError, KeyError, TypeError):
                        pass
    superseded = set()
    for key, record in records.items():
        if record['effective'] > now:
            continue
        for refid, refsent, refsender in record['references']:
            previous = records.get(refid)
            if previous and (previous['sender'] != refsender or previous['sent'] != refsent):
                conflicts.update((key, refid))
            # Strictly increasing reference times preclude a valid cycle.
            superseded.add(refid)
    if conflicts:
        issues.append('NWS alert identity/revision conflict; records withheld')
    items = [dict(r, kind='alert') for key, r in records.items()
             if key not in superseded | conflicts and r['message_type'] != 'Cancel'
             and r['effective'] <= now < r['expires']]
    severity = {'Extreme': 0, 'Severe': 1, 'Moderate': 2, 'Minor': 3, 'Unknown': 4}
    items.sort(key=lambda r: (severity.get(r['properties'].get('severity'), 4), -r['sent'], r['id']))
    return result('partial' if issues else 'ok', items, sorted(set(issues)), source='NWS', checked=now,
                  evidence=data)


def alerts(point, client, clock):
    """Confirm NWS coverage before a point-filtered alert query; do not cache alerts."""
    literal = f'{point[0]:.4f},{point[1]:.4f}'
    coverage, _, _ = client.get(weather_source.NWS + '/points/' + literal)
    if (coverage.get('type') != 'Feature' or not isinstance(coverage.get('properties'), dict)
            or not coverage['properties'].get('forecastZone')):
        raise ValueError('NWS coverage unverified')
    data, _, _ = client.get(heat_adv.NWS_ALERTS_URL, {'point': literal, 'status': 'actual'})
    return alerts_from(data, clock())


def weather(point, client, clock):
    """Reuse W16 selection and cache safeguards without resolving the location again."""
    data = weather_lookup.lookup(f'{point[0]} {point[1]}', resolved=point, client=client, clock=clock)
    issues = ['Weather cached; provider failed'] if 'failed' in data['delivery'] else []
    return result('partial' if issues else 'ok', [dict(kind='weather', data=data)], issues)


def fire(point, client, clock):
    """Read bounded existing wildfire snapshots, with separate field provenance."""
    from . import wildfire_lookup as w, wildfire_settings as settings
    from .wildfire_store import Store
    from shapely.geometry import Point
    config = settings.load()
    if not config['enabled']:
        return result('unavailable', issues=['Fire category disabled'])
    deadline = min(client.deadline, time.monotonic() + CATEGORY_SECONDS)
    with Store(settings.database_path()) as store:
        store.db.execute('PRAGMA busy_timeout=500')
        store.db.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
        store.db.execute('BEGIN')
        if store.db.execute('PRAGMA quick_check(1)').fetchone()[0] != 'ok':
            raise ValueError('Wildfire cache integrity failure')
        for source in ('zones', 'egp', 'incidents', 'perimeters'):
            count = store.db.execute('SELECT count(*) FROM features WHERE source=?', (source,)).fetchone()[0]
            if count > MAX_LOCAL_RECORDS:
                raise ValueError('Wildfire cache exceeds briefing bounds')
        if not w.point_zones(store.features('zones'), *point):
            return result('unavailable', issues=['Fire outside installed zone coverage'])
        statuses = w.health(store, ('zones', 'egp', 'incidents', 'perimeters'), config, clock())
        issues = []
        for status in statuses:
            status['max_age'] = config['boundary_interval']*2 if status['source'] == 'zones' else config['stale_after']
            fetched = status.get('fetched')
            if status.get('error') or status.get('stale') or fetched is None or fetched > clock():
                issues.append('Fire cache coverage stale/failed/incomplete')
        radius = min(15, config['maximum_radius_miles'])
        found = []
        for record in w.incidents(store).values():
            if time.monotonic() >= deadline:
                raise TimeoutError('Fire read deadline')
            eligible_perimeters = []
            for perimeter in record['perimeters']:
                p = perimeter['properties']
                if p.get('attr_IrwinID') and p.get('poly_IRWINID') and w.identifier(p['attr_IrwinID']) != w.identifier(p['poly_IRWINID']):
                    issues.append('Conflicting perimeter associations excluded')
                    continue
                eligible_perimeters.append(perimeter)
            distance = w.matches(dict(record, perimeters=eligible_perimeters), Point(point[1], point[0]), point, radius)
            if distance is None:
                continue
            details = {name: w.fire_detail(record, name, statuses, config, clock())
                       for name in ('acreage', 'containment', 'perimeter', 'updated')}
            if any(d['conflict'] or d['freshness'] != 'recent' or d['partial'] for d in details.values()):
                issues.append('Fire fields stale/unknown/conflicting; see !fire')
            found.append(dict(kind='fire', id=record['id'], name=record['name'], distance_miles=distance,
                              details=details, origin='existing cache; nearby map distance, not threat extent'))
        found.sort(key=lambda r: (r['distance_miles'], r['id']))
        limit = min(3, config['max_results'])
        if len(found) > limit:
            issues.append('Additional nearby fire records omitted')
        return result('partial' if issues else 'ok', found[:limit], sorted(set(issues)),
                      sources=statuses, radius_miles=radius, total=len(found), live_checked=False,
                      stale_after=config['stale_after'])


def water(point, client, clock):
    """Use verified installed inventory and observations; never infer a live link."""
    from . import gauge_data, gauge_lookup, water_local, water_settings
    from .nearby_river_stations import haversine_miles
    config = water_settings.load()
    if not config['enabled']:
        return result('unavailable', issues=['Water category disabled'])
    root, pointer, stations = gauge_data.load_inventory(config)
    if len(stations) > MAX_LOCAL_RECORDS:
        raise ValueError('Water inventory exceeds briefing bounds')
    issues = ['Water installed coverage only; live not checked']
    observations_available = True
    try:
        values = gauge_data.load_observations(root, pointer, clock(), config['reading_max_age'])
    except gauge_lookup.FAILURES:
        values = {}
        observations_available = False
        issues.append('Water observations unavailable or incompatible')
    found = []
    for sid, station in stations.items():
        if time.monotonic() >= client.deadline:
            raise TimeoutError('Water read deadline')
        geometry = station.get('geometry') or {}
        xy = geometry.get('coordinates', [])
        if (geometry.get('type') != 'Point' or len(xy) < 2
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in xy[:2])
                or not -180 <= xy[0] <= 180 or not -90 <= xy[1] <= 90):
            continue
        distance = haversine_miles(*point, xy[1], xy[0])
        if distance <= config['nearby_radius_miles']:
            if len(values.get(sid, [])) > MAX_SERIES:
                raise ValueError('Station series exceed briefing bounds; use !gauge')
            rows = gauge_lookup.installed_rows(values, sid, clock(), config)
            found.append(dict(kind='water', id=sid, distance_miles=distance, readings=rows,
                              eligible_readings=sum(r['usable'] for r in rows) if observations_available else None,
                              origin='installed last-known; nearby does not imply upstream'))
    found.sort(key=lambda r: (r['distance_miles'], r['id']))
    limit = min(3, config['max_results'])
    if len(found) > limit:
        issues.append('Additional nearby water stations omitted')
    if water_local.read_json(root / 'inventory.json') != pointer:
        raise ValueError('Water inventory changed during briefing')
    return result('partial', found[:limit], issues, total=len(found),
                  radius_miles=config['nearby_radius_miles'], live_checked=False,
                  reading_max_age=config['reading_max_age'], observations_available=observations_available)


READERS = dict(alerts=alerts, weather=weather, fire=fire, water=water)
