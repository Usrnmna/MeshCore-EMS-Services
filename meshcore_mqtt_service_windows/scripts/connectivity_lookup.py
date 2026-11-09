"""Bounded reference connectivity from verified, reviewed routing generations."""
from contextlib import contextmanager
import os
import re
import sqlite3
import sys
import time

from . import dataset_paths, water_local, water_settings
from .response_text import MESSAGE_BYTES

SOURCE = 'NHDPlusV2'
NETWORK = 'NHDPlusV2_USGS_wmadata'
MAX_ROWS = 21
SQL_SECONDS = 3
FAILURES = (OSError, ValueError, KeyError, TypeError, RuntimeError, sqlite3.Error)


def parse(command, text):
    """Preserve exact IDs; names are exact source names with optional region selection."""
    if command not in {'downstream', 'tributaries'} or not isinstance(text, str):
        raise ValueError('Unknown connectivity command')
    if len(text.encode()) > 150 or any(not c.isprintable() for c in text):
        raise ValueError('Query must be printable and at most 150 bytes')
    words = text.split()
    if not words or words == ['help']:
        return {'help': True}
    if command == 'tributaries' and words[0] == 'name':
        region = None
        if 'region' in words[1:]:
            index = words.index('region', 1)
            if index != len(words)-2:
                raise ValueError('Use name NAME [region REGION]')
            region = words[-1]
            words = words[:index]
        if len(words) < 2:
            raise ValueError('Waterbody name required')
        return {'name': ' '.join(words[1:]), 'region': region}
    if len(words) != 1:
        raise ValueError('Use an exact station ID or NHDPlusV2:REACH-ID')
    token = words[0]
    if token.startswith(SOURCE + ':') and re.fullmatch(r'[0-9]+', token[len(SOURCE)+1:]):
        return {'reach': token[len(SOURCE)+1:]}
    if command == 'downstream' and re.fullmatch(r'[A-Za-z0-9]+-[A-Za-z0-9-]+', token):
        return {'station': token}
    raise ValueError('Use an exact station ID or NHDPlusV2:REACH-ID')


@contextmanager
def routing(config):
    """Verify routing bytes and dependency pins; open read-only with a SQL time bound."""
    root = water_settings.collection(config)
    folder, manifest, pointer = water_local.generation(root, 'routing', ['routing.sqlite'])
    if manifest.get('network') != NETWORK:
        raise ValueError('Unsupported routing source')
    pins = {'routing': pointer}
    for kind in ('inventory', 'network', 'link_review'):
        expected = manifest.get(kind + '_pointer')
        if expected is None:
            if kind != 'link_review' or (root / (kind + '.json')).exists():
                raise ValueError('Routing dependency absent or changed')
            pins[kind] = None
            continue
        _, dependency, actual = water_local.generation(root, kind)
        if actual != expected:
            raise ValueError('Incompatible routing generation')
        if kind in ('network', 'link_review') and dependency.get('inventory_pointer') != manifest['inventory_pointer']:
            raise ValueError('Incompatible station inventory')
        if kind == 'link_review' and dependency.get('network_pointer') != manifest['network_pointer']:
            raise ValueError('Incompatible link review')
        pins[kind] = actual
    configured = water_settings.data_root(config) / 'basin_plans'
    basin = dataset_paths.resolve('basin_plans', configured, configured=configured,
        defaults=(water_settings.ROOT / '../data/basin_plans',))
    basin_pointer = water_local.read_json(basin / 'sources.json')
    if basin_pointer != manifest.get('basin_pointer'):
        raise ValueError('Routing region source changed')
    path = folder / 'routing.sqlite'
    before = water_local.signature(path)
    db = water_local.readonly(path)
    deadline = time.monotonic() + SQL_SECONDS
    db.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
    try:
        yield db
        for kind, expected in pins.items():
            current = water_local.read_json(root / (kind + '.json')) if (root / (kind + '.json')).exists() else None
            if current != expected:
                raise ValueError('Routing generation changed during query')
        if water_local.signature(path) != before or water_local.read_json(basin / 'sources.json') != basin_pointer:
            raise ValueError('Routing source changed during query')
    finally:
        db.close()


def reach(db, identifier):
    """Fetch exact text identity without numeric conversion or name-based joining."""
    row = db.execute('SELECT reach_id,enabled,flow_direction,terminal,tidal,divergence,feature_type FROM reaches WHERE reach_id=?', (identifier,)).fetchone()
    return dict(row) if row else None


def limitations(record):
    """Retain source qualifications independently of connection eligibility."""
    flags = set()
    if record['tidal'] == 1:
        flags.add('tidal')
    elif record['tidal'] not in (0,):
        flags.add('tidal unknown')
    if record['divergence'] in (1, 2):
        flags.add('divergence')
    elif record['divergence'] != 0:
        flags.add('divergence unknown')
    if record['feature_type'] == 'Coastline':
        flags.add('coastline excluded')
    if record['enabled'] != 1 or record['flow_direction'] != 'With Digitized':
        flags.add('direction/enabled unreviewed')
    return flags


def permitted(record):
    """Require the same enabled, digitized river direction used by routing construction."""
    return record is not None and record['enabled'] == 1 and record['flow_direction'] == 'With Digitized' and record['feature_type'] != 'Coastline'


def format_result(heading, identifiers=(), flags=(), partial=False):
    """Keep qualifications essential and explicitly disclose any omitted identifiers."""
    identifiers = sorted(set(identifiers))
    budget = MESSAGE_BYTES - len(('@' + os.environ.get('MESHCORE_SENDER', 'Reader') + ' ').encode())
    core = heading + ('; ' + ','.join(sorted(set(flags))) if flags else '')
    for count in range(len(identifiers), -1, -1):
        prefix = core + ('; partial' if partial or count < len(identifiers) else '')
        result = prefix + ('; ' + ','.join(SOURCE + ':' + value for value in identifiers[:count]) if count else '')
        if len(result.encode()) <= budget and (count or not identifiers):
            return result
    return 'Connectivity result exceeds reply limit; partial/unresolved.'


def explore(db, command, identifier):
    """Inspect one adjacency only; repeated IDs and cycles cannot trigger traversal."""
    origin = reach(db, identifier)
    if origin is None:
        return 'Reach ID not found in installed routing.'
    flags = limitations(origin)
    if not permitted(origin):
        return format_result('Connectivity withheld', flags=flags)
    if command == 'downstream':
        rows = db.execute('SELECT * FROM flow_connections WHERE from_reach_id=? ORDER BY to_reach_id LIMIT ?', (identifier, MAX_ROWS)).fetchall()
    else:
        rows = db.execute('SELECT * FROM tributary_connections WHERE downstream_reach_id=? ORDER BY upstream_reach_id LIMIT ?', (identifier, MAX_ROWS)).fetchall()
        excluded = db.execute("SELECT status FROM flow_connections WHERE to_reach_id=? AND status != 'published_node_connection' LIMIT 1", (identifier,)).fetchone()
        if excluded:
            flags.add('excluded incoming links')
    partial = len(rows) == MAX_ROWS
    targets, seen = set(), set()
    terminal = False
    for row in rows:
        row = dict(row)
        target = row['to_reach_id'] if command == 'downstream' else row['upstream_reach_id']
        if target in seen:
            flags.add('duplicate edges')
        seen.add(target)
        if command == 'downstream':
            status = row['status']
            if (status == 'source_terminal' and origin['terminal'] == 1
                    and row['evidence_class'] == 'published_node_key_join'):
                terminal = True
                continue
            eligible = status == 'published_node_connection' and row['evidence_class'] == 'published_node_key_join'
        else:
            eligible = row['relationship'] == 'confluence_incoming_branch' and row['evidence_class'] == 'published_node_key_join'
            confluences = db.execute('SELECT DISTINCT relationship,evidence_class FROM tributary_connections WHERE upstream_reach_id=? AND downstream_reach_id=? LIMIT 2', (target, identifier)).fetchall()
            if len(confluences) != 1:
                flags.add('conflicting confluence')
                eligible = False
        # Check the whole pair even when the bounded adjacency result ends in
        # the middle of duplicate records. Identical duplicates are harmless;
        # conflicting classifications cannot establish a directed connection.
        source_id, target_id = (identifier, target) if command == 'downstream' else (target, identifier)
        edges = db.execute('SELECT DISTINCT status,evidence_class FROM flow_connections WHERE from_reach_id=? AND to_reach_id=? LIMIT 2', (source_id, target_id)).fetchall()
        if len(edges) > 1:
            flags.add('conflicting edges')
        eligible = (eligible and len(edges) == 1 and edges[0]['status'] == 'published_node_connection'
                    and edges[0]['evidence_class'] == 'published_node_key_join')
        destination = reach(db, target) if target else None
        if destination is not None:
            flags.update(limitations(destination))
            if command == 'tributaries' and destination['terminal'] == 1:
                flags.add('terminal/edge conflict')
                eligible = False
        if not eligible or not permitted(destination):
            flags.add('excluded/unresolved')
            if command == 'downstream' and status == 'direction_or_enabled_requires_review':
                flags.add('direction/enabled unreviewed')
            if command == 'downstream' and status == 'coastline_connection_not_river_routing':
                flags.add('coastline excluded')
            continue
        if target == identifier:
            flags.add('self-cycle')
        targets.add(target)
    if len(targets) > 1:
        flags.add('branches')
    if command == 'downstream' and origin['terminal'] == 1 and targets:
        return format_result('Terminal/edge conflict; withheld', flags=flags)
    if terminal:
        return format_result('Verified source terminal', flags=flags, partial=partial)
    if not targets:
        return format_result('No supported next refs; unresolved' if command == 'downstream' else 'No confluence refs in local coverage', flags=flags, partial=partial)
    return format_result('Next refs; one hop' if command == 'downstream' else 'Confluence refs; one hop', targets, flags, partial)


def lookup(command, text, config=None):
    """Resolve exact station/reach or disambiguate a named source reach without inference."""
    query = parse(command, text)
    if query.get('help'):
        return ('!downstream AGENCY-ID or NHDPlusV2:ID; one hop' if command == 'downstream' else
                '!tributaries NHDPlusV2:ID or name NAME [region REGION]')
    config = water_settings.load() if config is None else config
    if not config['enabled']:
        return 'Water commands disabled.'
    with routing(config) as db:
        if 'station' in query:
            records = db.execute('SELECT source_reach_id,status FROM station_routing_coverage WHERE station_id=? LIMIT 2', (query['station'],)).fetchall()
            if len(records) != 1 or records[0]['status'] not in water_local.SUPPORTED_PATH_STATUSES:
                return 'Station link missing, conflicting or unsupported; withheld.'
            identifier = records[0]['source_reach_id']
        elif 'name' in query:
            sql = 'SELECT reach_id FROM reaches WHERE name=?'
            args = [query['name']]
            if query['region']:
                sql += ' AND reach_id IN (SELECT reach_id FROM reach_regions WHERE region=?)'
                args.append(query['region'])
            records = db.execute(sql + ' ORDER BY reach_id LIMIT ?', (*args, MAX_ROWS)).fetchall()
            if not records:
                return 'No exact NHDPlusV2 name/region match.'
            if len(records) != 1:
                return format_result('Choose exact NHDPlusV2 reach', [r[0] for r in records], partial=len(records)==MAX_ROWS)
            identifier = records[0][0]
        else:
            identifier = query['reach']
        return explore(db, command, identifier)


def main(command, argv=None):
    """Run the dedicated lookup without subscriptions or source mutations."""
    try:
        print(lookup(command, ' '.join(sys.argv[1:] if argv is None else argv)))
        return 0
    except FAILURES:
        print('Connectivity unavailable or invalid; use help. No link inferred.')
        return 1
