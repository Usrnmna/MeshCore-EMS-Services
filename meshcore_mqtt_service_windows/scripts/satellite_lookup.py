"""Bounded read-only satellite identities and operation references; no tracking imports."""
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import sys
import time
from . import dataset_paths

ROOT = Path(__file__).resolve().parents[1]
LIMIT = 20
RETIRED = {'retired', 'decommissioned', 're-entered', 'decayed', 'future', 'not launched', 'end of mission'}


def read_json(path):
    """Bound metadata before decoding it."""
    if path.stat().st_size > 8 * 1024 * 1024:
        raise ValueError('Catalog metadata exceeds limit')
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError('Invalid catalog metadata')
    return value


def selection():
    """Honor installed satellite settings, shared roots, and managed removal."""
    shared = dataset_paths.data_root()
    override = os.environ.get('MESHCORE_SATELLITE_SETTINGS')
    settings = Path(override).resolve() if override is not None else ROOT / 'satellite-settings.json'
    configured = ROOT.parent / 'data/satellites'
    filename = 'satellites.sqlite3'
    if settings.exists() or override is not None:
        database = (settings.parent / read_json(settings)['database']).resolve()
        configured, filename = database.parent, database.name
        config = settings.parent / 'config.json'
        value = read_json(config).get('dataset_root') if config.is_file() else None
        if value is not None:
            if not isinstance(value, str) or not Path(value).is_absolute() or '.datasets' in Path(value).parts:
                raise ValueError('Invalid satellite dataset root')
            shared = Path(value).resolve()
    configured = configured.resolve()
    known = {(ROOT.parent / 'data/satellites').resolve(), shared / 'satellites', dataset_paths.data_root() / 'satellites'}
    if os.environ.get('MESHCORE_RUNTIME_DIR'):
        known.add((Path(os.environ['MESHCORE_RUNTIME_DIR']).parent / 'data/satellites').resolve())
    registry_path = shared / 'datasets.json'
    managed_path = configured.is_relative_to(shared / '.datasets')
    if '.datasets' in configured.parts and not managed_path:
        raise ValueError('Managed satellite path outside selected data root')
    registry = read_json(registry_path) if registry_path.exists() and (configured in known or managed_path) else None
    if managed_path and registry is None:
        raise ValueError('Managed satellite registry unavailable')
    receipt = None
    if registry is not None:
        if registry.get('schema') != 1 or not isinstance(registry.get('datasets'), dict):
            raise ValueError('Unsupported dataset registry')
        entry = registry['datasets'].get('satellites')
        if managed_path and entry is None:
            raise ValueError('Managed satellite generation unavailable')
        if 'satellites' in registry['datasets']:
            if not isinstance(entry, dict):
                raise ValueError('Invalid satellite dataset entry')
            active = entry['active']
            if active is None:
                raise ValueError('Satellite dataset explicitly removed')
            if not isinstance(active, dict):
                raise ValueError('Invalid satellite generation')
            selected = dataset_paths.checked_path(shared, active['path'])
            parts = Path(active['path'].replace('\\', '/')).parts
            if len(parts) != 4 or parts[:2] != ('.datasets', 'satellites') or parts[-1] != 'content':
                raise ValueError('Invalid satellite generation path')
            if managed_path and configured != selected:
                raise ValueError('Incompatible satellite generation')
            configured = selected
            receipt_path = dataset_paths.checked_path(shared, active['receipt'])
            if receipt_path != configured.parent / 'receipt.json':
                raise ValueError('Invalid satellite receipt')
            receipt = read_json(receipt_path)
            if receipt.get('schema') != 1 or receipt.get('dataset') != 'satellites' or receipt.get('path') != active['path']:
                raise ValueError('Incompatible satellite generation')
            # The installed satellite collection has no generation dependencies.
            if receipt.get('dependencies') != {} or not isinstance(receipt.get('files'), dict):
                raise ValueError('Incompatible satellite dependencies')
            filename = 'satellites.sqlite3'
    return dataset_paths.checked_path(configured, filename), registry, receipt


@contextmanager
def catalog():
    """Pin a read transaction; validate schema, integrity and managed database hash."""
    path, registry, receipt = selection()
    before = path.stat()
    if before.st_size > 64 * 1024 * 1024:
        raise ValueError('Satellite catalog exceeds limit')
    if receipt is not None:
        if Path(str(path) + '-wal').exists() or Path(str(path) + '-journal').exists():
            raise ValueError('Managed satellite catalog is not immutable')
        evidence = receipt['files'][path.name]
        if before.st_size != evidence.get('bytes', evidence.get('byte_count')) or hashlib.sha256(path.read_bytes()).hexdigest() != evidence['sha256']:
            raise ValueError('Satellite integrity failure')
    db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    deadline = time.monotonic() + 4
    db.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
    try:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        if db.execute('PRAGMA user_version').fetchone()[0] != 1:
            raise ValueError('Unsupported satellite schema')
        try:
            db.execute('SELECT satellite_id, norad_id, name, lifecycle, data_json FROM satellites LIMIT 0')
            db.execute('SELECT operation_id, satellite_id, catalog_status, catalog_updated_at, current_status, '
                       'last_evidence_status, evidence_at, conflicting_evidence, evidence_kind, data_json FROM operation_reference LIMIT 0')
        except sqlite3.DatabaseError as exc:
            raise ValueError('Unsupported satellite schema') from exc
        if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok' or db.execute('PRAGMA foreign_key_check').fetchone():
            raise ValueError('Satellite integrity failure')
        policy = db.execute("SELECT value FROM metadata WHERE key='status_max_age_days'").fetchone()
        if policy is None:
            raise ValueError('Missing status freshness policy')
        try:
            age = float(policy[0])
        except (ValueError, TypeError) as exc:
            raise ValueError('Invalid status freshness policy') from exc
        if not math.isfinite(age) or age <= 0:
            raise ValueError('Invalid status freshness policy')
        yield db, age
        if selection() != (path, registry, receipt) or path.stat().st_mtime_ns != before.st_mtime_ns:
            raise ValueError('Satellite generation changed; retry')
    finally:
        db.close()


def parse(command, text):
    """Exact names/aliases and NORAD IDs; operation IDs are never guessed."""
    if len(text.encode()) > 150 or any(not c.isprintable() for c in text):
        raise ValueError('Query must be printable and at most 150 bytes')
    words = text.split()
    if not words or words in (['help'], ['--help']):
        return {'help': True}
    result = {}
    if command == 'satfreq' and len(words) >= 3 and words[-2] == 'field':
        result['field'] = words[-1]
        words = words[:-2]
        if result['field'] not in {'uplink', 'downlink', 'mode', 'passband', 'status'}:
            raise ValueError('Unknown frequency field')
    if command == 'satfreq' and len(words) >= 3 and words[-2] == 'op':
        result['op'] = words[-1]
        words = words[:-2]
    if words[:1] == ['name'] and len(words) > 1:
        result['name'] = ' '.join(words[1:]).casefold()
    elif len(words) == 1 and re.fullmatch(r'[1-9][0-9]{0,8}', words[0]):
        result['norad'] = int(words[0])
    else:
        raise ValueError('Use NORAD-ID or name NAME; satfreq accepts op OPERATION-ID')
    return result


def status(row, age, now):
    """Evaluate dated evidence with the catalog policy; retrieval/orbits imply no activity."""
    if row['conflicting_evidence']:
        return 'unknown(conflict)'
    if not row['evidence_at']:
        return 'unknown(no evidence)'
    try:
        stamp = datetime.fromisoformat(row['evidence_at'].replace('Z', '+00:00'))
    except (ValueError, TypeError, AttributeError):
        return 'unknown(invalid date)'
    if stamp.utcoffset() is None:
        return 'unknown(undated)'
    days = (now - stamp).total_seconds() / 86400
    if days < 0:
        return 'unknown(future evidence)'
    if days > age:
        return 'unknown(stale ' + stamp.date().isoformat() + ')'
    required_kind = {'inactive': 'confirmed_failure', 'scheduled_off': 'operator_schedule'}.get(row['current_status'])
    if required_kind and row['evidence_kind'] != required_kind:
        return 'unknown(unqualified evidence)'
    return str(row['current_status']) + '@' + stamp.date().isoformat()


def lookup(command, text):
    """Return structured source records with no catalog writes or network calls."""
    query = parse(command, text)
    if query.get('help'):
        return {'message': '!sat NORAD-ID or name NAME' if command == 'sat' else '!satfreq NORAD-ID [op ID] [field uplink/downlink/mode/passband/status]; name NAME also accepted'}
    with catalog() as (db, age):
        if 'norad' in query:
            rows = db.execute('SELECT * FROM satellites WHERE norad_id=? LIMIT 21', (query['norad'],)).fetchall()
        else:
            rows = []
            for row in db.execute('SELECT * FROM satellites LIMIT 10001'):
                values = json.loads(row['data_json'])
                if query['name'] in {' '.join(str(n).split()).casefold() for n in [row['name']] + values.get('aliases', [])}:
                    rows.append(row)
                if len(rows) > LIMIT:
                    break
            if db.execute('SELECT count(*) FROM satellites').fetchone()[0] > 10000:
                raise ValueError('Name catalog exceeds limit; use NORAD-ID')
        if not rows:
            return {'message': 'Not in installed catalog; excluded/unknown is not inactive.'}
        if len(rows) != 1:
            if 'norad' in query:
                return {'message': 'Ambiguous NORAD ID; conflicting records. Unavailable.'}
            choices = sorted({str(r['norad_id']) for r in rows[:LIMIT] if r['norad_id'] is not None})
            for count in range(len(choices), 0, -1):
                message = 'Ambiguous name; choose NORAD-ID; partial choices: ' + ','.join(choices[:count])
                if fit(message) == message:
                    return {'message': message}
            return {'message': 'Ambiguous name; source identity unresolved. Use local --json.'}
        satellite = dict(rows[0])
        identity = json.loads(satellite['data_json'])
        for key in ('satellite_id', 'norad_id', 'name', 'lifecycle'):
            if key in identity and identity[key] != satellite[key]:
                raise ValueError('Conflicting satellite identity')
        validate_identifier(satellite['satellite_id'], 'satellite')
        satellite_label(satellite)
        if (satellite['lifecycle'] or '').casefold() in RETIRED:
            return {'message': satellite_label(satellite) + ': lifecycle=' + satellite['lifecycle'] + '; operations withheld.'}
        if query.get('op'):
            operations = db.execute('SELECT * FROM operation_reference WHERE satellite_id=? AND operation_id=? LIMIT 2', (satellite['satellite_id'], query['op'])).fetchall()
        else:
            operations = db.execute("SELECT * FROM operation_reference WHERE satellite_id=? AND json_extract(data_json,'$.superseded_by') IS NULL ORDER BY operation_id LIMIT 21", (satellite['satellite_id'],)).fetchall()
        records = []
        now = datetime.now(timezone.utc)
        for row in operations:
            # Retain decimal source tokens exactly instead of rounding through a
            # binary float. Structured attributes carry decimal values as strings.
            values = json.loads(row['data_json'], parse_float=str)
            if values['operation_id'] != row['operation_id'] or values['satellite_id'] != satellite['satellite_id']:
                raise ValueError('Conflicting operation identity')
            validate_identifier(row['operation_id'], 'operation')
            records.append(dict(row, attributes=values, evaluated_status=status(row, age, now)))
        return {'satellite': satellite, 'operations': records[:LIMIT], 'partial': len(records) > LIMIT,
                'command': command, 'field': query.get('field'), 'status_max_age_days': age,
                'status_evaluated_at': now.isoformat(), 'coverage': 'Installed catalog only; RF unverified'}


def validate_identifier(value, kind):
    """Reject identities that command parsing or radio formatting would rewrite."""
    if not isinstance(value, str) or not value or any(c.isspace() or not c.isprintable() or c == '|' for c in value):
        raise ValueError('Unsupported ' + kind + ' identifier; no identity inferred')


def satellite_label(satellite):
    """Retain source identity when a named record has no assigned NORAD number."""
    number = satellite['norad_id']
    if number is None:
        return 'source=' + satellite['satellite_id'] + '(NORAD unknown)'
    if type(number) is not int or not 0 < number < 1000000000:
        raise ValueError('Invalid NORAD identity')
    return str(number)


def fit(text):
    """Retain complete essential fields or explicitly withhold the reply."""
    text = ' '.join(str(text).replace('|', '/').split())
    budget = 150 - len(('@' + os.environ.get('MESHCORE_SENDER', 'Reader') + ' ').encode())
    return text if len(text.encode()) <= budget else 'Qualified result too long; narrow selection or use local --json.'


def frequency(value):
    """Render exact recorded Hz without rounding to a reduced MHz precision."""
    if value is None:
        return '?'
    if len(str(value)) > 64:
        raise ValueError('Recorded frequency exceeds precision limit')
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError('Invalid recorded frequency') from exc
    if not number.is_finite() or number <= 0:
        raise ValueError('Invalid recorded frequency')
    if abs(number.adjusted()) > 30 or number.as_tuple().exponent < -30:
        raise ValueError('Recorded frequency exceeds precision limit')
    # Decimal.normalize() can round with the ambient decimal context.
    text = format(number, 'f')
    return text.rstrip('0').rstrip('.') if '.' in text else text


def catalog_label(row, result):
    """Qualify a source-reported label separately from operational evidence."""
    label = str(row['catalog_status'] or 'unknown')
    stamp = row['catalog_updated_at']
    try:
        dated = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
        now = datetime.fromisoformat(result['status_evaluated_at'])
        if dated.utcoffset() is None:
            raise ValueError('Undated')
        days = (now - dated).total_seconds() / 86400
        qualification = 'future' if days < 0 else 'stale' if days > result['status_max_age_days'] else 'dated'
        return 'cat=' + label + '@' + dated.date().isoformat() + '(' + qualification + ')'
    except (ValueError, TypeError, AttributeError):
        return 'cat=' + label + '(undated)'


def render(result):
    """Separate catalog lifecycle from dated operation evidence and RF uncertainty."""
    if 'message' in result:
        return fit(result['message'])
    sat = result['satellite']
    operations = result['operations']
    prefix = satellite_label(sat) + ' life=' + str(sat['lifecycle'] or 'unknown') + '; RF unverified; '
    if result['command'] == 'sat':
        return fit(prefix + sat['name'] + '; catalog: ' + str(len(operations)) + ('+ ops' if result['partial'] else ' ops') + '; use !satfreq')
    if not operations:
        return fit(prefix + 'Operation unavailable for this satellite.')
    if len(operations) != 1:
        choices = [r['operation_id'] for r in operations]
        for count in range(min(len(choices), LIMIT), 0, -1):
            text = prefix + 'select op; ' + ('partial: ' if count < len(choices) or result['partial'] else '') + ','.join(choices[:count])
            if len(text.encode()) <= 150 - len(('@' + os.environ.get('MESHCORE_SENDER', 'Reader') + ' ').encode()):
                return fit(text)
        return fit(prefix + 'Operation IDs exceed radio limit; use local --json.')
    row = operations[0]
    v = row['attributes']
    # Satellite lifecycle is available through !sat; each operation reply retains
    # its stable ID and operational uncertainty even with a focused field selector.
    prefix = satellite_label(sat) + '; RF unverified; '
    if v.get('superseded_by'):
        return fit(prefix + row['operation_id'] + '; discontinued/superseded; frequencies withheld; replacement=' + str(v['superseded_by']))
    qualifiers = [row['operation_id'], row['evaluated_status'], 'TX auth unknown']
    if v.get('review_required'):
        qualifiers.append('review required')
    if not v.get('present_in_latest_source', False):
        qualifiers.append('source absent')
    if v.get('schedule'):
        qualifiers.append('schedule=' + str(v['schedule']))
    raw = v.get('raw') or {}
    if raw.get('unconfirmed'):
        qualifiers.append('source unconfirmed')
    if raw.get('frequency_violation') or json.loads(sat['data_json']).get('raw', {}).get('is_frequency_violator'):
        qualifiers.append('source frequency violation')
    qualifiers.append(','.join(v.get('scopes', [])) or 'category unknown')
    field = result.get('field')
    if field in (None, 'status'):
        qualifiers.append(catalog_label(row, result))
    if field in (None, 'mode'):
        qualifiers += ['mode=' + str(v.get('modulation') or '?'),
                       'protocol=' + (','.join(v.get('protocols', [])) or '?'),
                       'type=' + str(v.get('transmitter_type') or '?')]
        if v.get('source_mode') and v['source_mode'] != v.get('modulation'):
            qualifiers.append('source mode=' + v['source_mode'])
    for role in ('uplink', 'downlink'):
        if field not in (None, role):
            continue
        low, high = v.get(role + '_low_hz'), v.get(role + '_high_hz')
        if low is not None and high is not None and Decimal(frequency(high)) < Decimal(frequency(low)):
            raise ValueError('Reversed frequency bounds')
        qualifiers.append(('up=' if role == 'uplink' else 'dn=') + frequency(low) + (('-' + frequency(high)) if high is not None and high != low else '') + 'Hz')
        if role == 'uplink':
            if v.get('uplink_mode'):
                qualifiers.append('up mode=' + v['uplink_mode'])
            if v.get('uplink_availability') not in (None, 'unknown'):
                qualifiers.append('access=' + v['uplink_availability'])
    if field in (None, 'passband'):
        widths = [('passband_width_hz', 'passband'), ('occupied_bandwidth_hz', 'occupied'),
                  ('necessary_bandwidth_hz', 'necessary'), ('frequency_span_hz', 'span')]
        for key, label in widths:
            if v.get(key) is not None:
                qualifiers.append(label + '=' + frequency(v[key]) + 'Hz')
        if not any(v.get(key) is not None for key, _ in widths):
            qualifiers.append('bandwidth unknown')
        if v.get('inverting') is not None:
            qualifiers.append('inverting=' + str(v['inverting']))
    return fit(prefix + '; '.join(qualifiers))


def main(command, argv=None):
    """Dedicated programs return explicit unavailable responses without maintenance actions."""
    args = list(sys.argv[1:] if argv is None else argv)
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    structured = args[:1] == ['--json']
    if structured and os.environ.get('MESHCORE_REQUEST_ID'):
        print(fit('JSON is local-only; use an operation and field selector.'))
        return 0
    if structured:
        args = args[1:]
    try:
        result = lookup(command, ' '.join(args))
        print(json.dumps(result, ensure_ascii=False) if structured else render(result))
    except ValueError as exc:
        # These messages describe selection and validation, without filesystem paths.
        message = 'Satellite unavailable: ' + str(exc) if not isinstance(exc, json.JSONDecodeError) else 'Satellite metadata invalid'
        print(json.dumps({'error': message}) if structured else fit(message))
    except (OSError, TypeError, KeyError, IndexError, AttributeError, sqlite3.Error):
        message = 'Satellite catalog unavailable or invalid; use help.'
        print(json.dumps({'error': message}) if structured else fit(message))
    return 0
