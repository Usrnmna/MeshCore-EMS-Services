"""Named Basin Plan references, immediate CalWater parents and designated uses."""
import csv
import json
import os
import re
import sys

from . import basin_plan_data as data, water_settings
from .response_text import MESSAGE_BYTES

MAX_MATCHES = 20
LEVEL_LABELS = ('HR', 'HU', 'HA', 'HSA', 'SPW', 'PW')
HELP = {
    'waterway': '!waterway LOCATION or name NAME [region REGION] [source SERVICE/LAYER] or id BP:SERVICE/LAYER:OBJECT',
    'basin': '!basin LOCATION or parent BP:SERVICE/LAYER:OBJECT; CalWater HR/HU/HA/HSA/SPW/PW, not Board regions',
    'wateruse': '!wateruse BP:SERVICE/LAYER:OBJECT or name NAME [region REGION] [source SERVICE/LAYER]; [use CODE] [field name/description/status/notes]',
}


def parse(command, text):
    """Validate bounded exact-ID/name selectors before reading any data."""
    if command not in HELP or not isinstance(text, str):
        raise ValueError('Unknown Basin Plan command')
    if len(text.encode('utf-8')) > 150 or any(not c.isprintable() for c in text):
        raise ValueError('Query must be printable and at most 150 bytes')
    words = text.split()
    if not words or words in (['help'], ['--help']):
        return {'help': True}
    query = {}
    allowed = set() if command == 'basin' else ({'region', 'source'} if command == 'waterway' else {'region', 'source', 'use', 'field'})
    # Selectors are explicit trailing pairs; arbitrary remainder is never ignored.
    while len(words) >= 2 and words[-2] in allowed:
        key, value = words[-2:]
        if key in query:
            raise ValueError('Duplicate selector')
        query[key] = value
        words = words[:-2]
    if command == 'basin':
        if len(words) != 2 or words[0] != 'parent':
            raise ValueError('Use !basin parent BP:SERVICE/LAYER:OBJECT')
        token = words[1]
    elif words and words[0] == 'name':
        if len(words) < 2 or any(w in allowed for w in words[1:]):
            raise ValueError('Use name NAME [region REGION] [source SERVICE/LAYER]')
        query['name'] = ' '.join(words[1:])
        token = None
    else:
        if words and words[0] == 'id':
            words = words[1:]
        if len(words) != 1:
            raise ValueError('Use an exact BP:SERVICE/LAYER:OBJECT identity')
        token = words[0]
    if token is not None:
        match = re.fullmatch(r'BP:([A-Za-z0-9_-]+/[0-9]+):([A-Za-z0-9_{}.-]+)', token)
        if not match:
            raise ValueError('Use BP:SERVICE/LAYER:OBJECT; preserve source ID and zeroes')
        query['key'], query['object'] = match.groups()
    if query.get('field') not in (None, 'name', 'description', 'status', 'notes'):
        raise ValueError('Use field name, description, status or notes')
    if query.get('field') and not query.get('use'):
        raise ValueError('Select use CODE before field')
    return query


def region_matches(category, region):
    """Board selectors match complete regional categories; CalWater remains separate."""
    if region is None:
        return True
    if region.isdigit():
        return category.startswith(f'regions/{int(region):02d}_')
    return region == category or category.startswith('regions/') and region == category.split('/')[1]


def in_scope(entry, query):
    source = query.get('source')
    return (region_matches(entry['category'], query.get('region')) and
            (source is None or source in (entry['key'], entry['key'].rsplit('/', 1)[0])))


def resolve(collection, query, command):
    """Return exact source identities; name groups never merge or establish connectivity."""
    if 'key' in query:
        entry = collection.entries.get(query['key'])
        if not entry or not in_scope(entry, query):
            return [], False
        eligible = (data.level(entry) is not None if command == 'basin' else
                    entry['name'] in data.WATER_LAYERS or command == 'waterway' and data.level(entry) is not None)
        if not eligible:
            raise data.Unavailable('Identity is not an eligible source layer')
        record = collection.record(query['key'], query['object'])
        return ([(query['key'], record)] if record else []), False
    candidates = set()
    partial = False
    for row in collection.csv_rows('names.csv'):
        entry = collection.entries.get(row['dataset_key'])
        if entry is None or row['category'] != entry['category']:
            raise data.Unavailable('Name index source mismatch')
        index = data.level(entry)
        fields = {'wb_name', 'gnis_name'} if entry['name'] in data.WATER_LAYERS else (
            {data.OWN_NAMES[index]} if index is not None and command == 'waterway' else set())
        if (row['name_field'].lower() not in fields or row['name_status'] != 'published'
                or ' '.join(row['name'].split()).casefold() != query['name'].casefold()
                or not in_scope(entry, query)):
            continue
        ids = json.loads(row['sample_object_ids'])
        partial |= int(row['matching_records']) > len(ids)
        candidates.update((entry['key'], str(i)) for i in ids)
        if len(candidates) > MAX_MATCHES:
            candidates = set(sorted(candidates)[:MAX_MATCHES])
            partial = True
    # Index samples are discovery candidates, not a substitute for full membership.
    # Unique resolution is allowed only when the source reports complete coverage.
    if len(candidates) == 1 and not partial:
        key, identifier = next(iter(candidates))
        record = collection.record(key, identifier)
        if record is None:
            raise data.Unavailable('Name index membership mismatch')
        return [(key, record)], False
    return [(key, {'object_id_json': json.dumps(identifier)}) for key, identifier in sorted(candidates)], partial


def source_key(record, fields):
    values = data.attributes(json.loads(record['source_keys_json']))
    selected = [values.get(f) for f in fields]
    if any(v is None or isinstance(v, str) and not v.strip() for v in selected):
        return None
    return data.key_token(selected)


def dataset_failure(row):
    """Missing-field rows qualify the whole dataset, rather than one key group."""
    return row['source_key_json'] == '' and row['status'] in {
        'missing_source_fields', 'missing_target_fields', 'missing_both_fields'}


def parent(collection, key, record):
    """Read one recorded immediate parent, rejecting cycles, conflicts and skipped levels."""
    entry = collection.entries[key]
    child_level = data.level(entry)
    result = {'kind': 'parent', 'level': data.LEVEL_NAMES[child_level], 'level_code': LEVEL_LABELS[child_level]}
    candidates = set()
    statuses = set()
    for row in collection.relations('calwater_hierarchy'):
        if row['source_dataset'] != key:
            continue
        fields = [f.strip().lower() for f in row['source_fields'].split(';')]
        token = source_key(record, fields)
        if not dataset_failure(row) and (token is None or token != row['source_key_json']):
            continue
        target = collection.entries.get(row['target_dataset'])
        if (not target or target['category'] != entry['category'] or
                target['key'].rsplit('/', 1)[0] != key.rsplit('/', 1)[0]):
            statuses.add('unsupported parent source')
            continue
        target_level = data.level(target)
        # Installed SPW/PW-to-Unit rows describe ancestors, not immediate parents.
        if child_level in (4, 5) and target_level == 1:
            continue
        expected_field = 'hrc' if child_level == 1 else data.LEVEL_FIELDS[child_level]
        if (child_level == 0 or target_level != child_level - 1 or fields != [expected_field]
                or row['target_fields'].strip().lower() != data.LEVEL_FIELDS[target_level]
                or row['relationship_type'] != 'calwater_hierarchy'):
            statuses.add('conflicting hierarchy or cycle')
            continue
        if row['status'] != 'verified_code_parent':
            statuses.add(row['status'])
            continue
        members = collection.matching_members(target['key'], [data.LEVEL_FIELDS[target_level]], row['target_key_json'])
        if len(members) != 1 or int(row['target_records']) != len(members):
            statuses.add('ambiguous or missing parent')
            continue
        candidates.add(data.identity(target['key'], json.loads(members[0]['object_id_json'])))
    if statuses or len(candidates) > 1:
        result.update(status='unresolved', qualifications=sorted(statuses or {'conflicting parents'}))
    elif child_level == 0:
        result.update(status='root', qualifications=['CalWater hierarchy root; not a Water Board region'])
    elif not candidates:
        result.update(status='unresolved', qualifications=['missing recorded parent'])
    else:
        result.update(status='verified', parent=next(iter(candidates)), parent_level=data.LEVEL_NAMES[child_level - 1],
                      parent_level_code=LEVEL_LABELS[child_level - 1])
    return result


def translated(values, schema, field):
    """Translate only a published coded-value domain, retaining the original raw code."""
    value = values.get(field)
    metadata = next((f for f in schema.get('fields', []) if f['name'].lower() == field), {})
    domain = metadata.get('domain') or {}
    matches = [v['name'] for v in domain.get('codedValues', []) if data.key_token([v['code']]) == data.key_token([value])]
    return {'code': value, 'description': matches[0] if len(matches) == 1 else None}


def uses(collection, key, record, query):
    """Expand only published WBF_ID joins within one service and category."""
    entry = collection.entries[key]
    token = source_key(record, ['wbf_id'])
    result = {'kind': 'uses', 'uses': [], 'qualifications': [], 'field': query.get('field')}
    if token is None:
        result['qualifications'] = ['missing published designation key']
        return result
    targets = {}
    for row in collection.relations('beneficial_uses'):
        if row['source_dataset'] != key or (row['source_key_json'] != token and not dataset_failure(row)):
            continue
        target = collection.entries.get(row['target_dataset'])
        if (not target or target['category'] != entry['category'] or target['name'] not in data.USE_LAYERS
                or target['key'].rsplit('/', 1)[0] != key.rsplit('/', 1)[0]
                or row['source_fields'].lower() != 'wbf_id' or row['target_fields'].lower() != 'wbf_id'
                or row['relationship_type'] != 'beneficial_uses'
                or not dataset_failure(row) and row['target_key_json'] != token):
            result['qualifications'].append('unsupported designation relationship')
            continue
        if row['status'] != 'matched_key_group':
            result['qualifications'].append(row['status'])
            continue
        targets.setdefault(target['key'], set()).add(int(row['target_records']))
    if result['qualifications']:
        return result  # A conflicting relationship cannot silently lose its qualification.
    for target_key, counts in targets.items():
        rows, schema = collection.table(target_key)
        matching = [data.attributes(r) for r in rows if data.key_token([data.attributes(r).get('wbf_id')]) == token]
        if counts != {len(matching)} or not matching:
            raise data.Unavailable('Designation relationship membership conflict')
        for row in matching:
            if query.get('use') is not None and row.get('bu_code') != query['use']:
                continue
            result['uses'].append({'id': data.identity(target_key, row[collection.entries[target_key]['object_id_field'].lower()]),
                'attributes': row, 'status': translated(row, schema, 'butype_id'),
                'notes': translated(row, schema, 'bunote_id')})
            if len(result['uses']) > MAX_MATCHES:
                raise data.Unavailable('Too many designations; select use CODE')
    if not targets:
        result['qualifications'].append('missing designation relationship; coverage incomplete')
    elif not result['uses']:
        result['qualifications'].append('no recorded classification for selected use')
    result['uses'].sort(key=lambda r: r['id'])
    return result


def lookup(command, text, config=None):
    """Return a bounded structured reference result with all designation attributes intact."""
    query = parse(command, text)
    if query.get('help'):
        return {'kind': 'help', 'text': HELP[command]}
    config = water_settings.load() if config is None else config
    if not config['enabled']:
        return {'kind': 'message', 'text': 'Water commands disabled.'}
    with data.Collection(config) as collection:
        matches, partial = resolve(collection, query, command)
        if not matches:
            return {'kind': 'message', 'text': 'No exact record in installed Basin Plan coverage.'}
        ids = [data.identity(key, json.loads(record['object_id_json'])) for key, record in matches]
        if len(matches) != 1 or partial:
            return {'kind': 'choices', 'ids': ids, 'partial': partial}
        key, record = matches[0]
        entry = collection.entries[key]
        common = {'id': ids[0], 'category': entry['category'], 'source': key, 'resolved_by_name': 'name' in query,
                  'snapshot': collection.manifest['snapshot_id'], 'coverage': 'installed sources only',
                  'source_limitations': collection.manifest.get('limitations', [])}
        if command == 'basin':
            result = parent(collection, key, record)
        elif command == 'wateruse':
            result = uses(collection, key, record, query)
        else:
            index = data.level(entry)
            result = {'kind': 'waterway', 'name': record.get('wb_name') or record.get('gnis_name') or query.get('name'),
                      'level': data.LEVEL_NAMES[index] if index is not None else None,
                      'source_keys': json.loads(record['source_keys_json']),
                      'qualifications': ['Basin Plan reference; no directed connectivity established']}
        return dict(common, **result)


def clean(value):
    """Prevent source strings from becoming optional-field or line separators on radio."""
    return ' '.join(str(value).replace('|', '/').split())


def fit(text, fallback='Qualified result exceeds radio limit; narrow query.'):
    """Withhold an oversized essential result; never clip identities or qualifications."""
    budget = MESSAGE_BYTES - len(('@' + os.environ.get('MESHCORE_SENDER', 'Reader') + ' ').encode('utf-8'))
    text = clean(text)
    if len(text.encode('utf-8')) <= budget:
        return text
    return fallback if len(fallback.encode('utf-8')) <= budget else 'Result withheld; radio limit.'


def render(result):
    """Format one radio reply; detailed source descriptions remain available in CLI JSON."""
    kind = result['kind']
    if kind in {'help', 'message'}:
        return fit(result['text'], 'Use exact BP:SERVICE/LAYER:OBJECT; see command help.')
    if kind == 'choices':
        heading = 'Ambiguous; choose exact ID; local coverage'
        for count in range(len(result['ids']), 0, -1):
            suffix = '; partial' if result['partial'] or count < len(result['ids']) else ''
            text = heading + suffix + ': ' + ', '.join(result['ids'][:count])
            if fit(text, ''):
                return clean(text)
        return 'Ambiguous; IDs exceed radio limit. Narrow region/source.'
    category = result['category']
    region = 'Board ' + category.split('/')[1].split('_')[0] if category.startswith('regions/') else (
        'CalWater' if category.startswith('hydrologic_boundaries/') else category)
    if kind == 'waterway':
        text = f"Local BP ref; no connectivity; {region}; {result['id']}"
        if result.get('level'):
            text += '; ' + result['level']
        name = result.get('name')
        return fit(text + '; ' + name, fit(text)) if name else fit(text)
    if kind == 'parent':
        heading = 'CalWater ' + result['level_code'] + '; not Board regions; '
        if result['status'] == 'verified':
            return fit(heading + result['parent_level_code'] + ' parent ' + result['parent'])
        return fit(heading + ('hierarchy root' if result['status'] == 'root' else
                              'parent unresolved: ' + ', '.join(result['qualifications'])))
    named = result.get('resolved_by_name', False)
    followup = fit(f"Name resolved; query !wateruse {result['id']} for designations.",
                   fit(f"Use !wateruse {result['id']}")) if named else None
    heading = f"BP designations; no safety/access/conditions; {region}; "
    if named:
        heading += result['id'] + '; '
    if result['qualifications']:
        unresolved = fit('Uses unresolved; ' + result['id']) if named else None
        return fit(heading + '; '.join(result['qualifications']), unresolved or
                   'Designations unavailable/unresolved; no safety/access/conditions implied.')
    records = result['uses']
    parts = []
    for record in records:
        values = record['attributes']
        code = values.get('bu_code') or 'classification missing'
        status = record['status']
        notes = record['notes']
        label = (f"{code} region={values.get('region_key', 'unknown')} type={status['code']}" +
                 f"({status['description'] or 'unresolved'})" +
                 f" note={notes['code']}({notes['description'] or 'unresolved'})")
        known = {'objectid', 'wbf_id', 'bu_id', 'bucode_id', 'bu_code', 'bu_name', 'bu_desc',
                 'butype_id', 'bunote_id', 'region_key', 'region_name'}
        extra = [f'{key}={clean(value)}' for key, value in values.items() if key not in known and value is not None]
        if extra:
            label += '; ' + '; '.join(extra)
        if result.get('field'):
            field = result['field']
            value = values.get('bu_name' if field == 'name' else 'bu_desc') if field in {'name', 'description'} else record[field if field == 'notes' else 'status']['description']
            label += '; ' + field + '=' + (clean(value) if value is not None else 'unresolved')
        else:
            label += '; text omitted'
        parts.append(label)
    # Every displayed designation includes its unresolved/translated type and note.
    for count in range(len(parts), 0, -1):
        partial = f'partial {count}/{len(parts)}; ' if count < len(parts) else ''
        text = heading + partial + '; '.join(parts[:count])
        if fit(text, ''):
            return clean(text)
    return followup or fit('Designation details exceed radio limit; use CODE/field or local --json. No safety/access/conditions implied.')


def main(command, argv=None):
    """Run a dedicated read-only command; JSON is a local CLI option, not a radio selector."""
    args = list(sys.argv[1:] if argv is None else argv)
    structured = bool(args and args[0] == '--json')
    if structured:
        args = args[1:]
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    try:
        result = lookup(command, ' '.join(args))
        print(json.dumps(result, ensure_ascii=False) if structured else render(result))
        return 0
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, csv.Error, EOFError) as exc:
        text = str(exc) if isinstance(exc, data.Unavailable) else 'Basin Plan source/query unavailable or invalid; use help.'
        print(json.dumps({'error': text}) if structured else fit(text))
        # An unavailable reference is a valid radio response. Nonzero exits make
        # the service replace stdout with its generic process-failure message.
        return 0
