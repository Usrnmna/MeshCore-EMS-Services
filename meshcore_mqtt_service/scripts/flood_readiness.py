"""Internal discovery and requirement-scoped environmental input readiness.

discover(source=None, limit=20, config=None) lists existing context and reviewed
profile selectors. assess(scope, intended_use, profile=None, now=None, config=None)
requires an exact scope dictionary (kind, source, id, generation, and basin level).
No model, pilot basin, engine, thresholds, transformations or defaults are chosen.
Suitability is limited to recorded reviewed requirements and pinned artifacts;
raw numerical reconstruction and predictive validation are outside this contract.
"""
from datetime import datetime, timezone
import json
import math

from . import flood_readiness_data as data, flood_evidence, flood_catalog, water_settings
from . import dataset_paths, reference_policy
from .flood_reference_data import EvidenceError

MAX_RESULT_BYTES = 128 * 1024
QUALIFICATION = ('Input requirements assessment only; not model approval, engine readiness, '
                 'predictive validation, a forecast or operational suitability. '
                 'Acquisition and preparation remain deferred; no data are transformed.')

# Fields identify required questions, not acceptable thresholds. Every criterion
# must be supplied by a reviewed application profile; no generic numeric defaults.
COMMON = ('variable', 'units', 'horizontal_crs', 'spatial_coverage', 'uncertainty', 'quality_flags')
CATEGORIES = {
    'terrain': ('vertical_datum', 'resolution', 'accuracy', 'channel_geometry',
                'bathymetry', 'depressions', 'spill_points', 'barriers'),
    'soil_properties': ('conductivity', 'storage', 'layering', 'soil_depth'),
    'soil_moisture': ('soil_depth', 'spatial_support', 'representativeness'),
    'land_cover': ('imperviousness', 'runoff_parameters', 'resistance_parameters'),
    'forcing': ('spatial_support', 'time_step', 'time_alignment'),
    'boundaries': ('station_ids', 'gauge_zero', 'vertical_datum', 'time_step',
                   'time_alignment', 'hydrograph_completeness', 'downstream_conditions', 'tidal_backwater'),
    'structures': ('inventory_completeness', 'operations', 'effective_period'),
    'validation': ('independence', 'event_identity', 'time_alignment', 'vertical_datum', 'gauge_zero'),
}
INPUT_KINDS = {
    'terrain': ('terrain_and_channel_geometry',),
    'soil_properties': ('soil_hydraulic_properties',),
    'soil_moisture': ('soil_moisture_observations',),
    'land_cover': ('land_cover_parameters',),
    'forcing': ('rainfall_forcing', 'snowmelt_forcing'),
    'boundaries': ('boundary_hydrographs',),
    'structures': ('structure_operations',),
    'validation': ('independent_event_observations',),
}
DOMAIN_CHECKS = ('reporting_boundary_association', 'contributing_catchments', 'reaches_stations',
                 'cross_border_inputs', 'nested_area_accounting', 'tributary_flow_accounting')
UNSUPPORTED = {
    'landslide_station_metadata': 'Station metadata are not numerical soil moisture.',
    'hillside_sensor': 'Hillside proximity does not establish floodplain representativeness.',
    'soil_moisture_as_infiltration': 'Soil moisture is not an infiltration rate.',
    'saturation_as_zero_infiltration': 'Saturation does not establish zero infiltration.',
    'latest_gauge_reading': 'Latest readings are not event hydrographs or calibration histories.',
    'snow_depth_as_water_equivalent': 'Snow depth does not establish snow-water equivalent.',
    'weather_alert': 'Alerts are not rainfall grids.',
    'fire_perimeter': 'Fire perimeters are not burn-severity or infiltration maps.',
    'river_connectivity': 'Connectivity does not establish travel times or overflow paths.',
    'static_hazard': 'Static hazards are not terrain, boundary conditions or independent validation.',
    'scenario_footprint': 'Published scenarios are not independent observed validation or model inputs.',
    'dem_as_gauge_zero': 'Generic elevation cannot resolve gauge zero or historical scenario references.',
}
STATES = ('not_installed', 'removed', 'unavailable', 'unknown', 'unreviewed',
          'incomplete', 'incompatible', 'suitable', 'not_applicable')


def _result(status, **fields):
    """Keep predictive validation and input readiness separate in every response."""
    return dict(schema_version=1, status=status, qualification=QUALIFICATION,
                predictive_validation='not_assessed', engine_ready=False, **fields)


def _error(exc):
    """Map read failures to stable reasons without exposing paths or raw exceptions."""
    if isinstance(exc, reference_policy.ReferenceUseError):
        return 'incompatible', 'reference_only_source_forbidden'
    reason = flood_catalog.issue(exc)
    if reason == 'managed_removal':
        return 'removed', reason
    if reason == 'not_installed':
        return 'not_installed', reason
    if 'limit' in reason:
        return 'limit', reason
    if 'incompatible' in reason or 'conflicting' in reason:
        return 'incompatible', reason
    return 'unavailable', reason


def _run(operation, config):
    """Pin one bounded read transaction, including error and partial responses."""
    reader = None
    try:
        reader = data.Snapshot(water_settings.load() if config is None else water_settings.validate(config))
        try:
            result = operation(reader)
        except flood_catalog.READ_ERRORS as exc:
            state, reason = _error(exc)
            result = _result(state, reasons=[reason], input_ready=False, records=[])
        reader.finish()
        encoded = json.dumps(result, ensure_ascii=False, allow_nan=False).encode('utf-8')
        if len(encoded) > MAX_RESULT_BYTES:
            raise EvidenceError('result_limit')
        return result
    except flood_catalog.READ_ERRORS as exc:
        state, reason = _error(exc)
        return _result(state, reasons=[reason], input_ready=False, records=[])


def _limit(value):
    """Validate bounded discovery size before resolving or reading any source."""
    if type(value) is not int or not 1 <= value <= 20:
        raise ValueError('limit must be 1..20')


def _context(reader, dataset, pointer, meaning):
    """Inspect a source manifest without certifying its data or modelling suitability."""
    row = dict(source=dataset, artifact=pointer, role='context_only', qualification=meaning,
               integrity='unchecked', suitability='unreviewed')
    try:
        root = reader.resolve(dataset)
        path = root / pointer
        if not reader.exists(path):
            row.update(state='not_installed')
            return row
        pin = reader.document(path)
        if not isinstance(pin, dict):
            raise EvidenceError('invalid_source_pointer')
        if dataset == 'landslide':
            manifest = pin
            row['integrity'] = 'unchecked_manifest'
        else:
            file = dataset_paths.checked_path(root, pin['manifest_path'])
            expected = dict(sha256=pin.get('sha256', pin.get('manifest_sha256')),
                            byte_count=pin.get('byte_count', file.stat().st_size))
            if dataset == 'basin_plans':
                # Source manifests include large embedded schemas. Discovery only
                # hashes these bounded bytes and exposes the pointer's identity;
                # it does not parse geometry or claim source semantic validation.
                reader.checked(file, expected)
                manifest = dict(snapshot_id=pin.get('snapshot_id'),
                                counts=dict(datasets=pin.get('dataset_count')))
            else:
                manifest = reader.document(file, expected)
            row['integrity'] = 'manifest_only'
        if not isinstance(manifest, dict):
            raise EvidenceError('invalid_source_manifest')
        row.update(state='installed', generation=manifest.get('generation', manifest.get('snapshot_id')),
                   generation_created_at=manifest.get('created_at_utc'),
                   metadata={key: manifest[key] for key in ('kind', 'scope', 'counts', 'retention',
                       'coverage_note', 'station_count', 'telemetry_verified', 'checked_on', 'notes') if key in manifest})
    except flood_catalog.READ_ERRORS as exc:
        state, reason = _error(exc)
        if state == 'limit':
            raise
        row.update(state=state, reason=reason)
    return row


def discover(*, source=None, limit=20, config=None):
    """List exact profile selectors and installed context, never infer assessability."""
    _limit(limit)
    if source is not None:
        flood_evidence.identifier(source)

    def operation(reader):
        specs = (
            ('basin_plans', 'sources.json', 'CalWater reporting boundaries are not computational catchments.'),
            ('usgs_water', 'inventory.json', 'Station identity and location do not establish model-domain association.'),
            ('usgs_water', 'observations.json', UNSUPPORTED['latest_gauge_reading']),
            ('usgs_water', 'routing.json', UNSUPPORTED['river_connectivity']),
            ('flood_impacts', 'static.json', UNSUPPORTED['scenario_footprint']),
            ('flood_hazards', 'static.json', UNSUPPORTED['static_hazard']),
            ('landslide', 'manifest.json', UNSUPPORTED['landslide_station_metadata']),
        )
        records = [_context(reader, *spec) for spec in specs if source is None or source == spec[0]]
        try:
            reader.open_profiles()
            profiles = [dict(header) for header in reader.profiles
                        if source is None or header['scope']['source'] == source]
            profile_state = 'installed'
        except flood_catalog.READ_ERRORS as exc:
            profile_state, reason = _error(exc)
            if profile_state == 'limit':
                raise
            profiles = []
            records.append(dict(source='flood_readiness', state=profile_state, reason=reason,
                                suitability='unknown', role='requirements'))
        # Profile headers are discovery only: even a declared profile can fail its
        # artifact review, associations, compatibility or requirement checks.
        profiles.sort(key=lambda h: (h['scope']['source'], h['id']))
        total = len(records) + len(profiles)
        shown_profiles = profiles[:limit]
        shown_records = records[:max(0, limit - len(shown_profiles))]
        return _result('partial' if total > limit else 'ok', records=shown_records,
                       profiles=shown_profiles, total=total, partial=total > limit,
                       profile_state=profile_state, discovery_only=True,
                       input_ready=False, unsupported_substitutions=UNSUPPORTED,
                       adapter_limits=['Local pointing terrain requires separate model-purpose review.',
                           'Weather adapters are not invoked; no forcing history is acquired.',
                           'Context manifests do not establish actual variable quality or input completeness.'])

    return _run(operation, config)


def _same(left, right):
    """Keep types and leading zeroes distinct, including booleans versus numbers."""
    return type(left) is type(right) and data.review_digest(left) == data.review_digest(right)


def _missing(value):
    """Reject missing values even inside quantities and source-reference objects.

    An empty flag list can explicitly record no flags. Empty spatial coverage
    and empty requirements are handled separately, never interpreted as N/A.
    """
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().lower() in ('', 'unknown', 'unavailable', 'unreviewed')
    if isinstance(value, dict):
        return not value or any(_missing(item) for item in value.values())
    if isinstance(value, list):
        return any(_missing(item) for item in value)
    return False


def _criterion(actual, rule):
    """Check an explicit reviewed constraint without unit conversion or interpolation."""
    if not isinstance(rule, dict):
        return 'unknown', 'requirement_unresolved'
    op = rule.get('op')
    if op == 'not_applicable':
        return ('not_applicable', None) if isinstance(rule.get('justification'), str) and rule['justification'].strip() else ('unknown', 'unjustified_not_applicable')
    if op not in ('eq', 'max', 'min', 'contains', 'allowed', 'covers') or 'value' not in rule or rule['value'] is None:
        return 'unknown', 'requirement_unresolved'
    expected = rule['value']
    if _missing(actual):
        return 'incomplete', 'evidence_missing'
    if _missing(expected):
        return 'unknown', 'requirement_unresolved'
    if op == 'eq':
        passed = _same(actual, expected)
    elif op in ('max', 'min'):
        if (not isinstance(actual, dict) or type(actual.get('value')) not in (int, float)
                or type(expected) not in (int, float) or not isinstance(rule.get('unit'), str)
                or _missing(rule['unit'])):
            return 'unknown', 'numeric_requirement_or_evidence_invalid'
        if actual.get('unit') != rule['unit']:
            return 'incompatible', 'units_incompatible'
        if not math.isfinite(actual['value']) or not math.isfinite(expected):
            return 'unknown', 'numeric_requirement_or_evidence_invalid'
        passed = actual['value'] <= expected if op == 'max' else actual['value'] >= expected
    elif op in ('contains', 'allowed'):
        if not isinstance(actual, list) or not isinstance(expected, list):
            return 'unknown', 'set_requirement_or_evidence_invalid'
        if len(actual) > data.MAX_RECORDS or len(expected) > data.MAX_RECORDS:
            raise EvidenceError('criterion_record_limit')
        if op == 'contains' and not expected:
            return 'unknown', 'empty_requirement'
        required, available = (expected, actual) if op == 'contains' else (actual, expected)
        passed = all(any(_same(item, other) for other in available) for item in required)
    else:
        try:
            a, b = (flood_evidence.instant(actual[k]) for k in ('start', 'end'))
            c, d = (flood_evidence.instant(expected[k]) for k in ('start', 'end'))
            passed = a <= c <= d <= b
        except (ValueError, TypeError, KeyError):
            return 'unknown', 'time_coverage_invalid'
    return ('suitable', None) if passed else ('incompatible', 'requirement_not_met')


def _subject(header, **fields):
    """Bind reviews to exact scope, use and profile identity, plus their local subject."""
    return dict(profile=header['id'], scope=header['scope'], intended_use=header['intended_use'], **fields)


def _requirement(reader, header, requirement, inputs, now):
    """Assess one input against reviewed requirements, retaining independent states."""
    if not isinstance(requirement, dict):
        raise EvidenceError('invalid_requirement')
    identifier = flood_evidence.identifier(requirement['id'])
    category = requirement['category']
    if category not in CATEGORIES or type(requirement.get('critical')) is not bool:
        raise EvidenceError('invalid_requirement')
    row = dict(id=identifier, category=category, critical=requirement['critical'], state='unknown',
               reasons=[], integrity='unchecked', compatibility='unknown', suitability='unknown')
    if not reader.review(requirement.get('review'), _subject(header, requirement=identifier), requirement):
        row.update(state='unreviewed', reasons=['requirement_review_missing'])
        return row
    if requirement.get('not_applicable') is True:
        justification = requirement.get('justification')
        row.update(state='not_applicable' if isinstance(justification, str) and justification.strip() else 'unknown',
                   justification=justification)
        if row['state'] == 'unknown':
            row['reasons'].append('unjustified_not_applicable')
        return row
    criteria = requirement.get('criteria')
    time_mode = requirement.get('time_mode')
    if not isinstance(criteria, dict) or len(criteria) > 48 or time_mode not in ('static', 'event', 'current'):
        row['reasons'].append('requirements_unresolved')
        return row
    if category in ('soil_moisture', 'forcing', 'boundaries', 'validation') and time_mode == 'static':
        row['reasons'].append('time_dependent_input_requires_observation_or_event_coverage')
        return row
    required = set(COMMON + CATEGORIES[category])
    required.add('source_vintage' if time_mode == 'static' else 'time_coverage')
    if time_mode == 'current':
        age = requirement.get('max_age_seconds')
        if type(age) not in (float, int) or not math.isfinite(age) or age <= 0:
            row['reasons'].append('freshness_requirement_unresolved')
            return row
    if required - set(criteria):
        row['reasons'].extend('requirement_missing:' + name for name in sorted(required - set(criteria)))
        return row
    selector = requirement.get('input')
    if not isinstance(selector, dict) or set(selector) != {'source', 'id', 'generation'}:
        row['reasons'].append('exact_input_selection_required')
        return row
    for value in selector.values():
        flood_evidence.identifier(value)
    matches = [item for item in inputs if all(item[key] == value for key, value in selector.items())]
    if not matches:
        row.update(state='not_installed', reasons=['input_not_installed'])
        return row
    if len(matches) != 1:
        row.update(state='incompatible', reasons=['ambiguous_input_identity'])
        return row
    item = matches[0]
    row.update(input_id=item['id'], source=item.get('source'), generation=item.get('generation'),
               facts=item.get('facts'), qualifications=item.get('qualifications'),
               observed_at=item.get('observed_at'), source_date=item.get('source_date'),
               acquired_at=item.get('acquired_at'))
    if item.get('kind') not in INPUT_KINDS[category]:
        row.update(state='incompatible', reasons=['unsupported_substitution'],
                   qualification=UNSUPPORTED.get(item.get('kind'), 'Input type is not eligible for this requirement.'))
        return row
    if not reader.review(item.get('review'), _subject(header, requirement=identifier, input=selector), item):
        row.update(state='unreviewed', reasons=['input_association_or_suitability_review_missing'])
        return row
    if item.get('preparation') != 'verified':
        row.update(state='incomplete', reasons=['preparation_outstanding'])
        return row
    dependencies = data.bounded_list(item.get('dependencies'), 8)
    if not dependencies:
        row.update(state='incomplete', reasons=['numerical_artifact_evidence_missing'])
        return row
    if item['generation'] not in [d.get('generation') for d in dependencies if isinstance(d, dict)]:
        row.update(state='incompatible', reasons=['input_generation_not_pinned'])
        return row
    try:
        artifact_count = 0
        for entry in dependencies:
            artifact_count += reader.dependency(entry)
            metadata = reader.dependency_metadata[(entry['dataset'], entry['pointer'])]
            if metadata['retention'] == 'latest_values_only' and category in ('boundaries', 'validation'):
                row.update(state='incompatible', reasons=['latest_values_are_not_event_hydrographs'])
                return row
    except flood_catalog.READ_ERRORS as exc:
        state, reason = _error(exc)
        if state == 'limit' or reason == 'generation_changed':
            raise
        row.update(state=state, reasons=[reason], integrity='failed' if reason == 'integrity_failed' else 'unavailable')
        return row
    if artifact_count == 0:
        row.update(state='incomplete', reasons=['numerical_artifact_evidence_missing'])
        return row
    row['integrity'] = 'passed_consumed_artifacts'
    facts = item.get('facts')
    if not isinstance(facts, dict):
        row.update(state='incomplete', reasons=['facts_missing'])
        return row
    checks = {}
    for name, rule in sorted(criteria.items()):
        state, reason = _criterion(facts.get(name), rule)
        if name == 'time_coverage' and time_mode != 'static':
            if not isinstance(rule, dict) or rule.get('op') != 'covers':
                state, reason = 'unknown', 'temporal_coverage_required'
        if name == 'spatial_coverage' and state == 'suitable' and facts[name] == []:
            state, reason = 'incomplete', 'spatial_coverage_missing'
        if name in ('variable', 'units', 'horizontal_crs', 'vertical_datum') and state == 'suitable':
            if not isinstance(facts.get(name), str):
                state, reason = 'incomplete', 'source_definition_missing'
        if (category == 'validation' and name == 'independence'
                and state in ('suitable', 'not_applicable') and facts.get(name) is not True):
            state, reason = 'incompatible', 'validation_independence_not_established'
        checks[name] = dict(state=state, reason=reason)
    if time_mode == 'current':
        row['freshness'] = flood_evidence.observation_state(item.get('observed_at'), now, requirement['max_age_seconds'])
        if row['freshness'] != 'fresh':
            checks['freshness'] = dict(state='incomplete', reason='observation_' + row['freshness'])
        else:
            interval = dict(start=item['observed_at'], end=item['observed_at'])
            state, reason = _criterion(facts.get('time_coverage'), dict(op='covers', value=interval))
            if state != 'suitable':
                checks['observation_time_coverage'] = dict(state=state, reason=reason)
    else:
        row['freshness'] = 'not_applicable_' + time_mode
    row['checks'] = checks
    failed = [(key, check) for key, check in checks.items() if check['state'] not in ('suitable', 'not_applicable')]
    row['reasons'] = [key + ':' + check['reason'] for key, check in failed]
    row['compatibility'] = 'incompatible' if any(c['state'] == 'incompatible' for _, c in failed) else 'unknown' if failed else 'compatible'
    row['state'] = row['suitability'] = ('incompatible' if row['compatibility'] == 'incompatible'
                                      else 'incomplete' if failed else 'suitable')
    return row


def assess(scope, intended_use, *, profile=None, now=None, config=None):
    """Assess one explicitly selected scope/use; never select a pilot or default model."""
    selected_scope = data.scope(scope)
    flood_evidence.identifier(intended_use)
    if profile is not None:
        flood_evidence.identifier(profile)
    if now is None:
        now = datetime.now(timezone.utc).timestamp()
    if type(now) not in (int, float) or not math.isfinite(now):
        raise ValueError('Finite assessment time required')
    try:
        assessed_at = datetime.fromtimestamp(now, timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        raise ValueError('Assessment time outside supported range') from None

    def operation(reader):
        try:
            reader.open_profiles()
        except flood_catalog.READ_ERRORS as exc:
            state, reason = _error(exc)
            if state not in ('not_installed', 'removed'):
                raise
            return _result(state, scope=selected_scope, intended_use=intended_use, assessed_at=assessed_at,
                           input_ready=False, blockers=['reviewed_requirements_' + state], reasons=[reason],
                           records=[dict(category=c, state='unknown', reasons=['requirements_and_associations_missing'])
                                    for c in CATEGORIES])
        matches = [h for h in reader.profiles if h['scope'] == selected_scope and h['intended_use'] == intended_use
                   and (profile is None or h['id'] == profile)]
        base = dict(scope=selected_scope, intended_use=intended_use, assessed_at=assessed_at, input_ready=False)
        if len(matches) != 1:
            return _result('ambiguous' if matches else 'unknown', reasons=['explicit_profile_required' if matches else 'scope_or_use_not_reviewed'],
                           profiles=[h['id'] for h in matches], records=[], **base)
        header = matches[0]
        body = reader.artifact_document(header['path'])
        if not isinstance(body, dict):
            raise EvidenceError('invalid_profile')
        if any(body.get(key) != header[key] for key in ('id', 'scope', 'intended_use')):
            raise EvidenceError('incompatible_profile_identity')
        base.update(profile=header['id'], generation=reader.manifest['generation'], engine=body.get('engine'))
        blockers = []
        if not reader.review(body.get('review'), _subject(header), body):
            blockers.append('profile_unreviewed')
        domain = body.get('domain')
        if (not isinstance(domain, dict) or not isinstance(domain.get('id'), str)
                or not reader.review(domain.get('review'), _subject(header, domain=domain.get('id')), domain)):
            blockers.append('model_domain_association_unreviewed')
        else:
            flood_evidence.identifier(domain['id'])
            domain_identity = data.scope(domain.get('identity'))
            if domain_identity['kind'] != 'model_domain' or domain_identity['id'] != domain['id']:
                blockers.append('model_domain_identity_conflict')
            for name in DOMAIN_CHECKS:
                finding = domain.get(name)
                if (not isinstance(finding, dict) or finding.get('state') not in ('reviewed', 'not_applicable')
                        or not isinstance(finding.get('justification'), str) or not finding['justification'].strip()):
                    blockers.append('domain_unresolved:' + name)
            if selected_scope['kind'] == 'model_domain' and domain_identity != selected_scope:
                blockers.append('model_domain_identity_conflict')
            associations = data.bounded_list(domain.get('associations'), 32)
            if not associations:
                blockers.append('domain_identity_evidence_missing')
            bound_scope = selected_scope == domain_identity
            for association in associations:
                if not isinstance(association, dict):
                    raise EvidenceError('invalid_domain_association')
                flood_evidence.identifier(association['id'])
                if (not isinstance(association.get('from'), dict) or not isinstance(association.get('to'), dict)
                        or not reader.review(association.get('review'), _subject(header, association=association))):
                    blockers.append('domain_association_unreviewed:' + association['id'])
                    continue
                for endpoint in (association['from'], association['to']):
                    for field in ('kind', 'source', 'id', 'generation'):
                        flood_evidence.identifier(endpoint[field])
                if association['from'] == selected_scope and association['to'] == domain_identity:
                    bound_scope = True
            if not bound_scope:
                blockers.append('scope_to_domain_association_missing')
            dependencies = data.bounded_list(domain.get('dependencies'), 8)
            if not dependencies:
                blockers.append('domain_source_evidence_missing')
            for dependency in dependencies:
                reader.dependency(dependency)
            pinned_generations = {d['generation'] for d in dependencies} | {reader.manifest['generation']}
            if selected_scope['generation'] not in pinned_generations or domain_identity['generation'] not in pinned_generations:
                blockers.append('domain_identity_generation_not_pinned')
        assumptions = data.bounded_list(body.get('assumptions'), 32)
        for assumption in assumptions:
            if not isinstance(assumption, dict):
                raise EvidenceError('invalid_assumption')
            flood_evidence.identifier(assumption['id'])
            if not reader.review(assumption.get('review'), _subject(header, assumption=assumption['id']), assumption):
                blockers.append('assumption_unreviewed:' + assumption['id'])
        requirements = data.bounded_list(body.get('requirements'), 64)
        inputs = data.bounded_list(body.get('inputs'))
        for item in inputs:
            if not isinstance(item, dict):
                raise EvidenceError('invalid_input')
            for key in ('id', 'source', 'generation'):
                flood_evidence.identifier(item[key])
        if any(not isinstance(r, dict) for r in requirements):
            raise EvidenceError('invalid_requirement')
        ids = [flood_evidence.identifier(r['id']) for r in requirements]
        if len(set(ids)) != len(ids):
            raise EvidenceError('ambiguous_requirement_identity')
        missing = set(CATEGORIES) - {r['category'] for r in requirements}
        blockers.extend('category_unresolved:' + category for category in sorted(missing))
        records = [_requirement(reader, header, r, inputs, now) for r in requirements]
        blockers.extend('requirement:' + r['id'] for r in records if r['state'] not in ('suitable', 'not_applicable'))
        # No optional gap is hidden behind a ready summary. Critical flags explain
        # severity; readiness still means all stated requirements were satisfied.
        ready = not blockers
        base['input_ready'] = ready
        return _result('ready_for_stated_requirements' if ready else 'blocked', records=records,
                       blockers=blockers, domain=domain, assumptions=assumptions,
                       verified_artifacts=sorted(reader.verified),
                       outstanding=body.get('outstanding', []),
                       numerical_validation='not_performed_by_readiness_assessment', **base)

    return _run(operation, config)
