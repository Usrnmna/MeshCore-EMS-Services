"""Internal static flood-hazard discovery and point lookup; no command or network.

discover() and at_coordinate() accept exact source/product/version and recorded
region selectors. at_coordinate() also accepts a literal string feature_id and
optional angular coordinate uncertainty. Missing selections are not guessed.
Only reviewed local schema-1 collections are supported, not arbitrary provider
downloads. Source-native properties are returned unchanged alongside field views.
"""
from collections import Counter
import json
import math

from . import flood_evidence as evidence, flood_geometry as geometry
from . import flood_hazard_data as data, flood_catalog, water_settings
from .flood_reference_data import EvidenceError

MAX_RESULT_BYTES = 128 * 1024
QUALIFICATION = ('Static hazard references only; not current inundation, a forecast, '
                 'a safety finding, or an authoritative regulatory determination.')


def _arguments(source, product, version, region, feature_id, limit):
    """Bound literal selectors before opening any dataset; retain case and zeroes."""
    for value in (source, product, version, region, feature_id):
        if value is not None:
            evidence.identifier(value)
    if type(limit) is not int or not 1 <= limit <= evidence.MAX_RESULTS:
        raise ValueError('Result limit must be 1..20')
    if feature_id is not None and any(v is None for v in (source, product, version)):
        raise ValueError('Feature selection requires source, product and version')


def _result(status='ok', records=None, **fields):
    """Keep static evidence and missing-coverage semantics explicit in every result."""
    return dict(schema_version=1, evidence_class='static_flood_hazard', status=status,
                records=records or [], qualification=QUALIFICATION, **fields)


def _identity(product):
    """Use a tuple instead of concatenation so namespaced identities cannot collide."""
    return tuple(product[key] for key in ('source', 'product', 'version'))


def _select(reader, source, product, version, region):
    """Apply every selector before limits and detect duplicate exact product identities."""
    rows = [row for row in reader.products
            if all(value is None or row[key] == value for key, value in
                   (('source', source), ('product', product), ('version', version)))
            and (region is None or region in row['regions'])]
    duplicates = [key for key, count in Counter(map(_identity, rows)).items() if count > 1]
    if duplicates:
        raise EvidenceError('ambiguous_product_identity')
    return sorted(rows, key=_identity)


def _metadata(product):
    """Keep receipt time, study date, effective date, and source vintage independent."""
    keys = ('source', 'product', 'version', 'publication_status', 'regulatory_status',
            'regions', 'study_date', 'effective_date', 'source_vintage', 'retrieved_at',
            'source_url', 'qualifications', 'review_reference', 'evidence_files',
            'positional_accuracy')
    return {key: product.get(key) for key in keys}


def _error(exc):
    """Return stable reasons without exposing filesystem paths or raw exceptions."""
    reason = flood_catalog.issue(exc)
    if reason == 'managed_removal':
        return 'removed', reason
    if reason == 'not_installed':
        return 'not_installed', reason
    if 'limit' in reason:
        return 'limit', reason
    if 'incompatible' in reason:
        return 'incompatible', reason
    if 'ambiguous' in reason:
        return 'ambiguous', reason
    return 'unavailable', reason


def _run(config, operation):
    """Pin one query and withhold incomplete results on integrity or resource failure."""
    try:
        reader = data.Snapshot(water_settings.load() if config is None else water_settings.validate(config))
        result = operation(reader)
        reader.finish()
        result.update(generation=reader.manifest['generation'],
                      generation_created_at=reader.manifest.get('created_at_utc'),
                      verified_files=len(reader.verified),
                      integrity_scope='consumed artifacts only; not predictive validation')
        if len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode()) > MAX_RESULT_BYTES:
            return _result('limit', reasons=['structured_result_size_limit'], narrow_selection=True)
        return result
    except flood_catalog.READ_ERRORS as exc:
        status, reason = _error(exc)
        return _result(status, reasons=[reason])


def discover(*, source=None, product=None, version=None, region=None, limit=20, config=None):
    """List installed reviewed products; declared coverage is not point-level proof."""
    _arguments(source, product, version, region, None, limit)

    def query(reader):
        selected = _select(reader, source, product, version, region)
        records = []
        for row in selected[:limit]:
            reader.source_evidence(row)
            records.append(dict(_metadata(row), coverage=row['coverage'],
                                geographic_assessment='not_assessed', geometry_integrity='unchecked'))
        return _result('partial' if len(selected) > limit else 'ok' if selected else 'no_matching_product',
                       records, total=len(selected), omitted=max(0, len(selected)-limit))

    return _run(config, query)


def _relation(shape, point, tolerance, budget):
    """Use an explicitly angular uncertainty band; never imply measured accuracy."""
    budget.operation()
    if shape.boundary.distance(point) <= tolerance:
        return 'boundary_uncertain'
    return 'inside' if shape.contains(point) else 'outside'


def _features(reader, descriptor, budget):
    """Check every source feature, including nonmatches, before a negative finding."""
    document = reader.document(descriptor['path'])
    if len(document['features']) != descriptor['record_count']:
        raise EvidenceError('incomplete_feature_inventory')
    seen = set()
    for feature in document['features']:
        if (not isinstance(feature, dict) or feature.get('type') != 'Feature'
                or not isinstance(feature.get('properties'), dict)):
            raise EvidenceError('invalid_feature_properties')
        properties = feature['properties']
        identifier = properties.get(descriptor['id_field'])
        # Integer object IDs stay integers; string IDs retain their leading zeroes.
        if type(identifier) not in (str, int) or isinstance(identifier, str) and not identifier:
            raise EvidenceError('feature_identity_missing')
        if isinstance(identifier, str):
            evidence.identifier(identifier)
        key = (type(identifier), identifier)
        if key in seen:
            raise EvidenceError('ambiguous_feature_identity')
        seen.add(key)
        if isinstance(feature.get('geometry'), dict) and feature['geometry'].get('coordinates') == []:
            raise EvidenceError('geometry_empty')
        yield identifier, properties, geometry.polygon(document, feature, budget)


def _coverage(reader, product, point, tolerance, budget):
    """Require explicit complete mapped-coverage evidence for a negative zone result."""
    descriptor = product['coverage']
    if descriptor['path'] is None:
        return dict(state='unknown', complete=False, matches=[], reference=None, conflicting=False)
    matches = []
    for identity, properties, shape in _features(reader, descriptor, budget):
        relation = _relation(shape, point, tolerance, budget)
        state = properties.get(descriptor['state_field'])
        if state not in ('mapped', 'unmapped', 'unknown'):
            raise EvidenceError('unsupported_coverage_state')
        if relation != 'outside':
            matches.append(dict(id=identity, state=state, relation=relation, properties=properties))
    states = {row['state'] for row in matches}
    if any(row['relation'] == 'boundary_uncertain' for row in matches):
        state = 'boundary_uncertain'
    elif len(states) > 1:
        state = 'conflicting'
    else:
        state = next(iter(states)) if states else 'unknown'
    return dict(state=state, complete=descriptor['complete'], matches=matches,
                reference=descriptor['reference'], conflicting=len(states) > 1)


def _measurements(values, missing):
    """Expose numeric source values without coercion or borrowing another field's units.

    Explicit per-measurement unit/reference mappings override shared mappings even
    when missing. Invalid values stay in properties/recorded_fields with an issue;
    they are never converted to a numerical measurement or silently substituted.
    """
    measurements, invalid = [], []
    for kind in ('base_flood_elevation', 'depth'):
        if kind in missing:
            continue
        value = values[kind]
        if type(value) not in (int, float):
            invalid.append(kind)
            continue
        attributes = {}
        for name in ('units', 'vertical_reference'):
            specific = kind + '_' + name
            field = specific if specific in values else name
            attribute = None if field in missing else values.get(field)
            if attribute is not None and (not isinstance(attribute, str) or not attribute.strip()):
                invalid.append(field)
                attribute = None
            attributes[name] = attribute
        measurements.append(dict(kind=kind, recorded_value=value, **attributes,
            usable_for_calculation=False,
            qualification='Recorded source value only; no conversion or current-depth inference'))
    return measurements, sorted(set(invalid))


def _point_product(reader, product, point, tolerance, budget, feature_id):
    """Keep zone hits, source-native fields and independent coverage evidence together."""
    reader.source_evidence(product)
    coverage = _coverage(reader, product, point, tolerance, budget)
    descriptor = product['zones']
    matches = []
    found = 0
    for identity, properties, shape in _features(reader, descriptor, budget):
        if feature_id is not None and str(identity) != feature_id:
            continue
        found += 1
        relation = _relation(shape, point, tolerance, budget)
        if relation != 'outside':
            values = {name: properties.get(field) for name, field in descriptor['fields'].items()}
            fields = data.FIELDS + tuple(name for name in data.MEASUREMENT_FIELDS if name in values)
            missing = [name for name in fields if values.get(name) is None
                       or values.get(name) in descriptor.get('missing_values', {}).get(name, [])]
            measurements, invalid = _measurements(values, missing)
            matches.append(dict(id=identity, relation=relation, recorded_fields=values,
                                missing_fields=missing, invalid_fields=invalid,
                                measurements=measurements, properties=properties))
    if feature_id is not None and found > 1:
        raise EvidenceError('ambiguous_feature_identity')
    if feature_id is not None and not found:
        relation = 'unknown_feature'
    elif matches:
        relation = 'boundary_uncertain' if any(r['relation'] == 'boundary_uncertain' for r in matches) else 'inside'
    elif coverage['state'] == 'mapped' and coverage['complete'] and descriptor['complete']:
        relation = 'outside_selected_zone' if feature_id is not None else 'outside_selected_zones'
    elif coverage['state'] == 'unmapped':
        relation = 'unmapped'
    else:
        relation = 'coverage_' + ('partial' if coverage['state'] == 'mapped' else coverage['state'])
    issues = []
    if coverage['conflicting'] or matches and coverage['state'] == 'unmapped':
        issues.append('zone_coverage_conflict')
    if any(row['invalid_fields'] for row in matches):
        issues.append('measurement_fields_invalid')
    return dict(_metadata(product), relation=relation, coverage=coverage, matches=matches,
                total_matches=len(matches), issues=issues, zones_complete=descriptor['complete'],
                selected_feature_id=feature_id, overlapping_zones=len(matches) > 1,
                overlap_qualification='All matches retained independently; no combined risk classification')


def at_coordinate(latitude, longitude, *, source=None, product=None, version=None,
                  region=None, feature_id=None, uncertainty_degrees=0, limit=20, config=None):
    """Query recorded polygons, bounding products and matches after all selectors.

    limit caps returned products, zone matches and coverage matches per product.
    All selected inputs are assessed before truncation; counts disclose partial
    output. A geometry/resource failure withholds the entire query result.
    """
    _arguments(source, product, version, region, feature_id, limit)
    latitude, longitude = geometry.coordinates(latitude, longitude)
    if (type(uncertainty_degrees) not in (int, float) or not math.isfinite(uncertainty_degrees)
            or not 0 <= uncertainty_degrees <= .01):
        raise ValueError('Coordinate uncertainty must be 0..0.01 degrees')
    tolerance = max(geometry.BOUNDARY_TOLERANCE_DEGREES, uncertainty_degrees)

    def query(reader):
        selected = _select(reader, source, product, version, region)
        if not selected:
            return _result('no_matching_product', total=0, omitted=0,
                           latitude=latitude, longitude=longitude, crs='OGC:CRS84')
        _, Point, _, geometry_error = geometry.dependencies()
        point = Point(longitude, latitude)
        budget = geometry.Budget(reader.tick)
        records = []
        try:
            for row in selected:
                records.append(_point_product(reader, row, point, tolerance, budget, feature_id))
        except geometry_error:
            raise EvidenceError('geometry_operation_failed') from None
        partial = len(records) > limit
        records = records[:limit]
        for row in records:
            row['omitted_matches'] = max(0, len(row['matches'])-limit)
            row['matches'] = row['matches'][:limit]
            coverage = row['coverage']
            coverage['total_matches'] = len(coverage['matches'])
            coverage['omitted_matches'] = max(0, coverage['total_matches']-limit)
            coverage['matches'] = coverage['matches'][:limit]
            partial |= bool(row['omitted_matches'] or row['issues'] or not row['zones_complete']
                            or coverage['omitted_matches']
                            or not row['coverage']['complete']
                            or row['coverage']['state'] != 'mapped')
        return _result('partial' if partial else 'ok' if selected else 'no_matching_product', records,
                       total=len(selected), omitted=max(0, len(selected)-limit),
                       latitude=latitude, longitude=longitude, crs='OGC:CRS84',
                       boundary_tolerance_degrees=tolerance,
                       coordinate_uncertainty_degrees=uncertainty_degrees,
                       positional_accuracy='Not established by the computational boundary band',
                       multiple_products=len(selected) > 1,
                       comparison='Products and versions remain separate; no preferred or merged hazard zone')

    return _run(config, query)
