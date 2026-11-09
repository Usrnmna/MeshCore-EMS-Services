"""Internal flood references; no command entry point, network access, or model execution."""
import json

from . import flood_catalog as catalog, flood_evidence as evidence, water_settings

MAX_RESULT_BYTES = 128 * 1024
QUALIFICATION = 'Installed hypothetical references only; not current inundation, a prediction, or an all-clear.'
REGION_FIELDS = {'state': 'states', 'wfo': 'wfo', 'rfc': 'rfc', 'huc8': 'huc8'}


def _arguments(source, limit, region=None, library_region=None):
    """Validate literal internal arguments before touching any datasets."""
    evidence.identifier(source)
    if type(limit) is not int or not 1 <= limit <= evidence.MAX_RESULTS:
        raise ValueError('Result limit must be 1..20')
    if region is not None:
        evidence.identifier(region)
        key, separator, value = region.partition(':')
        if not separator or key not in REGION_FIELDS or not value:
            raise ValueError('Region must be state:CODE, wfo:ID, rfc:ID, or huc8:ID')
        evidence.identifier(value)
    if library_region is not None:
        evidence.identifier(library_region)


def _matches_region(properties, region):
    """Select recorded region fields; never assign Water Board regions by inferred overlap."""
    if region is None:
        return True
    key, value = region.split(':', 1)
    recorded = properties.get(REGION_FIELDS[key])
    return value in recorded.split(',') if key == 'state' and isinstance(recorded, str) else recorded == value


def _station(identifier):
    """Require explicit namespaces while preserving source spelling and leading zeroes."""
    evidence.identifier(identifier)
    agency, separator, number = identifier.partition('-')
    if not separator:
        raise ValueError('Explicit CATFIM, USGS, or NOAA station namespace required')
    evidence.station_id(agency, number)
    return agency


def _result(status='ok', records=None, reasons=None, **fields):
    """Construct a source-qualified result that never turns absence into a safety finding."""
    return dict(schema_version=1, status=status, source=catalog.SOURCE, records=records or [],
                reasons=reasons or [], qualification=QUALIFICATION, **fields)


def _run(config, source, operation):
    """Keep failures explicit, validate pins before return, and bound serialized results."""
    if source != catalog.SOURCE:
        return _result('unsupported', reasons=['unsupported_source'], requested_source=source)
    try:
        reader = catalog.Catalog(water_settings.load() if config is None else config)
        result = operation(reader)
        reader.finish()
        result.update(generation=reader.snapshot.manifest['generation'],
                      generation_created_at=reader.snapshot.manifest.get('created_at_utc'),
                      issues=list(dict.fromkeys(reader.issues)),
                      verified_files=len(reader.snapshot.verified),
                      integrity_scope='consumed artifacts only; not hydraulic validation')
        if reader.issues and result['status'] == 'ok':
            result['status'] = 'partial'
        encoded = json.dumps(result, ensure_ascii=False, allow_nan=False).encode('utf-8')
        if len(encoded) > MAX_RESULT_BYTES:
            return _result('limit', reasons=['structured_result_size_limit'],
                           generation=reader.snapshot.manifest['generation'],
                           withheld_records=len(result['records']), narrow_selection=True)
        return result
    except catalog.READ_ERRORS as exc:
        reason = catalog.issue(exc)
        status = 'limit' if 'limit' in reason else 'unavailable'
        return _result(status, reasons=[reason])


def coverage(*, region=None, source=catalog.SOURCE, limit=20, config=None):
    """Discover installed catalog records; region uses explicit recorded-field namespaces.

    Coverage is limited to the installed California-associated catalog. The total
    describes matching inventory records, not eligible models or complete geography.
    """
    _arguments(source, limit, region)

    def select(reader):
        reader.check_dependencies()
        rows = [p for p in reader.catalog if _matches_region(p, region)]
        rows.sort(key=lambda p: (p['ahps_lid'], str(p.get('oid', ''))))
        records = [reader.site_record(p) for p in rows[:limit]]
        status = 'unknown_region' if region and not rows else 'partial' if len(rows) > limit else 'ok'
        return _result(status, records, total=len(rows), omitted=max(0, len(rows)-limit),
                       region=region, coverage_scope='installed California-associated catalog',
                       provider_mapping_counts={s: sum(p.get('mapped') == v for p in rows)
                                                for s, v in (('mapped', 'yes'), ('unmapped', 'no'))},
                       provider_mapping_unknown=sum(p.get('mapped') not in ('yes', 'no') for p in rows))

    return _run(config, source, select)


def _find_sites(reader, station_id, region, catalog_object_id, library_region=None):
    """Retain ambiguous source rows; optional source object selection never collapses duplicates."""
    # An unsupported recorded link establishes a candidate needing qualification,
    # not a verified alias. Preserve that distinction instead of reporting unknown.
    matches = []
    for properties in reader.catalog:
        if station_id.startswith('NOAA-'):
            identity_matches = any(station_id == 'NOAA-'+r['gauge_lid'] for r in reader.site_links(properties)
                                   if library_region is None or r['library_region'] == library_region)
        else:
            identity_matches = station_id in reader.aliases(properties)
        object_matches = (catalog_object_id is None or properties.get('oid') is not None
                          and str(properties['oid']) == catalog_object_id)
        if identity_matches and object_matches and _matches_region(properties, region):
            matches.append(properties)
    return matches


def _library_scope(reader, library_region):
    """Do not claim a globally unique selection when a library index could not be inspected."""
    if library_region is not None:
        selected = reader.regions.get(library_region)
        if selected is None:
            return _result('unknown_region', reasons=['library_region_not_in_manifest'])
        if selected['state'] != 'available':
            return _result('unavailable', reasons=['library_index_unavailable'])
    elif any(r['state'] != 'available' for r in reader.regions.values()):
        return _result('unavailable', reasons=['incomplete_library_indexes_require_region_selection'])
    return None


def site(station_id, *, source=catalog.SOURCE, region=None, catalog_object_id=None, limit=20, config=None):
    """Look up an exact catalog/agency identity with independent installed-library findings."""
    agency = _station(station_id)
    _arguments(source, limit, region)
    if catalog_object_id is not None:
        evidence.identifier(catalog_object_id)
    if agency not in ('CATFIM', 'USGS', 'NOAA'):
        return _result('unsupported', reasons=['unsupported_station_namespace'])

    def select(reader):
        reader.check_dependencies()
        matches = _find_sites(reader, station_id, region, catalog_object_id)
        if not matches:
            if agency == 'NOAA' and (not reader.regions or any(r['state'] != 'available' for r in reader.regions.values())):
                return _result('unavailable', reasons=['station_relationship_indexes_unavailable'])
            return _result('unknown', reasons=['station_not_in_selected_inventory'])
        if len(matches) != 1:
            return _result('ambiguous', [reader.site_record(p) for p in matches[:limit]],
                           ['duplicate_or_conflicting_station_identity'], total=len(matches), omitted=max(0, len(matches)-limit))
        gauge_lid = station_id.partition('-')[2] if agency == 'NOAA' else None
        record = reader.site_record(matches[0], gauge_lid=gauge_lid)
        candidates = reader.candidates(matches[0], gauge_lid=gauge_lid)
        outcomes = [reader.evaluate(r) for r in candidates[:limit]]
        # Site lookup reports availability and reasons, not unqualified scenario details.
        record['scenario_availability'] = [{k: r[k] for k in ('source', 'id', 'library_region', 'eligible', 'reasons')}
                                           for r in outcomes]
        record['scenario_eligibility'] = ('partial' if len(candidates) > limit else
            'eligible' if any(r['eligible'] for r in outcomes) else 'ineligible' if outcomes else 'unavailable')
        record['omitted_candidates'] = max(0, len(candidates)-limit)
        return _result('partial' if len(candidates) > limit else 'ok', [record])

    return _run(config, source, select)


def _selected(reader, rows, selection):
    """Keep scenario selection atomic: an ineligible bracket cannot become a single endpoint."""
    outcomes = [reader.evaluate(r) for r in rows]
    if any(not r['eligible'] for r in outcomes):
        # Preserve identities and reasons but withhold all detailed bracket data.
        stripped = [{k: r[k] for k in ('source', 'id', 'library_region', 'eligible', 'reasons')} for r in outcomes]
        return _result('ineligible', stripped, selection=selection)
    if selection == 'bracket':
        versions = [(r['library_region'], r['source_prefix'], r['evidence']['scenario']['gauge_id'],
                     r['evidence']['scenario']['source_version'], r['evidence']['scenario']['model_version'],
                     r['evidence']['scenario']['scenario_reference'], r['network'], r['reach_id']) for r in outcomes]
        if versions[0] != versions[1]:
            identities = [{k: r[k] for k in ('source', 'id', 'library_region', 'eligible', 'reasons')} for r in outcomes]
            return _result('ineligible', identities, ['incompatible_bracket_versions_or_references'],
                           selection=selection, interpolation=False)
        for label, result in zip(('lower', 'upper'), outcomes):
            result['bracket_role'] = label
    return _result(records=outcomes, selection=selection, interpolation=False)


def scenario(source, scenario_id, *, library_region=None, config=None):
    """Select an exact source-qualified scenario; duplicate IDs require explicit library selection."""
    _arguments(source, 1, library_region=library_region)
    evidence.identifier(scenario_id)

    def select(reader):
        blocked = _library_scope(reader, library_region)
        if blocked is not None:
            return blocked
        rows = [r for r in reader.rows if r['scenario_id'] == scenario_id
                and (library_region is None or r['library_region'] == library_region)]
        if not rows:
            return _result('unavailable' if reader.issues else 'unknown', reasons=['scenario_not_in_usable_indexes'])
        if len(rows) > 1:
            return _result('ambiguous', [dict(source=source, id=r['scenario_id'], library_region=r['library_region'])
                                        for r in rows[:evidence.MAX_RESULTS]],
                           ['duplicate_scenario_identity'], total=len(rows), omitted=max(0, len(rows)-evidence.MAX_RESULTS))
        return _selected(reader, rows, 'exact_id')

    return _run(config, source, select)


def scenario_at_coordinate(source, scenario_id, latitude, longitude, *, library_region=None, config=None):
    """Test a WGS84 point against one explicitly selected, eligible hypothetical scenario.

    Selection and geometry share one pinned read transaction. No observation can
    select a scenario, and no boundary result establishes current flood conditions.
    """
    from . import flood_geometry
    latitude, longitude = flood_geometry.coordinates(latitude, longitude)
    _arguments(source, 1, library_region=library_region)
    evidence.identifier(scenario_id)

    def select(reader):
        blocked = _library_scope(reader, library_region)
        if blocked is not None:
            return blocked
        rows = [r for r in reader.rows if r['scenario_id'] == scenario_id
                and (library_region is None or r['library_region'] == library_region)]
        if len(rows) != 1:
            return _result('ambiguous' if rows else 'unavailable' if reader.issues else 'unknown',
                           reasons=['scenario_identity_not_unique_or_missing'])
        result = _selected(reader, rows, 'exact_id')
        if result['status'] != 'ok':
            return result
        budget = flood_geometry.Budget(reader.snapshot.tick)
        footprint = flood_geometry.selected_geometry(reader, rows[0], budget)
        result['records'][0]['point'] = flood_geometry.point_result(footprint, latitude, longitude, budget)
        return result

    return _run(config, source, select)


def stage_scenarios(station_id, stage, stage_units, *, source=catalog.SOURCE,
                    library_region=None, catalog_object_id=None, config=None):
    """Select exact stages or published brackets, never extrapolating or choosing another gauge."""
    agency = _station(station_id)
    _arguments(source, 1, library_region=library_region)
    number, unit = catalog.stage_number(stage), catalog.units(stage_units)
    if catalog_object_id is not None:
        evidence.identifier(catalog_object_id)
    if agency not in ('CATFIM', 'USGS', 'NOAA'):
        return _result('unsupported', reasons=['unsupported_station_namespace'])

    def select(reader):
        blocked = _library_scope(reader, library_region)
        if blocked is not None:
            return blocked
        sites = _find_sites(reader, station_id, None, catalog_object_id, library_region)
        if len(sites) != 1:
            return _result('ambiguous' if sites else 'unknown', reasons=['station_identity_not_unique'])
        gauge_lid = station_id.partition('-')[2] if agency == 'NOAA' else None
        links = [r for r in reader.site_links(sites[0])
                 if library_region is None or r['library_region'] == library_region]
        gauges = sorted({r['gauge_lid'] for r in links})
        if gauge_lid is None and len(gauges) > 1:
            return _result('ambiguous', [dict(station_id=evidence.station_id('NOAA', lid))
                                        for lid in gauges[:evidence.MAX_RESULTS]],
                           ['multiple_gauge_associations'], total=len(gauges), omitted=max(0, len(gauges)-evidence.MAX_RESULTS))
        rows = reader.candidates(sites[0], library_region, gauge_lid=gauge_lid)
        if not rows:
            return _result('unavailable', reasons=['installed_library_unavailable'])
        matching = [r for r in rows if r['stage_units'] in ('FT', 'ft', 'm') and catalog.units(r['stage_units']) == unit]
        if not matching:
            return _result('unsupported', reasons=['stage_units_not_in_library'])
        exact = [r for r in matching if catalog.stage_number(r['stage']) == number]
        selected = exact
        selection = 'exact_stage'
        if not exact:
            lower = [r for r in matching if catalog.stage_number(r['stage']) < number]
            upper = [r for r in matching if catalog.stage_number(r['stage']) > number]
            if not lower or not upper:
                return _result('out_of_range', reasons=['below_library' if not lower else 'above_library'])
            lo = max(catalog.stage_number(r['stage']) for r in lower)
            hi = min(catalog.stage_number(r['stage']) for r in upper)
            selected = [r for r in lower if catalog.stage_number(r['stage']) == lo]
            selected += [r for r in upper if catalog.stage_number(r['stage']) == hi]
            selection = 'bracket'
        expected = 1 if selection == 'exact_stage' else 2
        if len(selected) != expected:
            return _result('ambiguous', [dict(source=source, id=r['scenario_id'], library_region=r['library_region'])
                                        for r in selected[:evidence.MAX_RESULTS]],
                           ['multiple_published_candidates'], total=len(selected), omitted=max(0, len(selected)-evidence.MAX_RESULTS))
        return _selected(reader, selected, selection)

    return _run(config, source, select)
