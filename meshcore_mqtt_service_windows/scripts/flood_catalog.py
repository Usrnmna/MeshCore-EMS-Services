"""Read-only CatFIM source adapter for internal W10-B discovery and references."""
import csv
from decimal import Decimal, InvalidOperation
import gzip
import io
import json
import re
import stat
import zlib

from . import dataset_paths, flood_evidence as evidence, flood_reference_data as data

SOURCE = 'NOAA-CatFIM'
CATALOG = 'inputs/california_site_inventory.geojson.gz'
SOURCE_URL = 'https://maps.water.noaa.gov/server/rest/services/fim_libs/static_stage_based_catfim/FeatureServer/'
MAX_ROWS = 4096
MAX_REGIONS = 32
MAX_EXPANDED_BYTES = 32 * 1024 * 1024
MAX_FEATURE_BYTES = 16 * 1024 * 1024
SCENARIO_FIELDS = ('scenario_id', 'gauge_lid', 'stage', 'stage_units', 'fim_version',
                   'model_version', 'source_layer', 'source_stage_field', 'source_object_ids',
                   'source_url', 'evidence_class', 'event_valid_time', 'depth_status')
LINK_FIELDS = ('gauge_lid', 'usgs_id', 'reach_id', 'network', 'status', 'source_url')


def stage_number(value):
    """Accept finite decimal stages without rounding selection boundaries or converting units."""
    if type(value) not in (str, int, float):
        raise ValueError('Invalid stage')
    text = str(value)
    if len(text) > 32 or not re.fullmatch(r'[+-]?[0-9]+(?:\.[0-9]+)?', text):
        raise ValueError('Invalid stage')
    try:
        number = Decimal(text)
    except InvalidOperation:
        raise ValueError('Invalid stage') from None
    if not number.is_finite():
        raise ValueError('Invalid stage')
    return number


def units(value):
    """Recognize recorded foot spellings and metres; never perform a conversion."""
    if not isinstance(value, str) or value not in ('FT', 'ft', 'm'):
        raise ValueError('Unsupported stage units')
    return 'ft' if value in ('FT', 'ft') else value


def source_path(row, relative):
    """Support isolated library originals while retaining legacy generation paths."""
    prefix = row.get('source_prefix', '')
    if prefix and not re.fullmatch(r'libraries/[A-Za-z0-9_-]{1,80}/', prefix):
        raise data.EvidenceError('invalid_library_source_prefix')
    return prefix+relative


def issue(exc):
    """Return stable failure reasons without exposing exception paths or provider headers."""
    if isinstance(exc, data.EvidenceError):
        return exc.code
    if isinstance(exc, FileNotFoundError):
        return 'managed_removal' if str(exc).startswith('Dataset is not installed:') else 'file_unavailable'
    return 'metadata_unavailable_or_invalid'


READ_ERRORS = (OSError, ValueError, KeyError, TypeError, EOFError, OverflowError, RecursionError,
               csv.Error, zlib.error)


class Catalog:
    """Pin one generation and retain partial catalog utility when library evidence fails.

    Source JSON is cached only for this call. No acquisition, persistent cache,
    model execution, or MeshCore context is used. Eligible scenarios also undergo
    bounded geometry validation against their original source objects.
    """

    def __init__(self, config):
        self.snapshot = data.Snapshot(config)
        self.cache = {}
        self.library_presence = {}
        self.expanded_remaining = MAX_EXPANDED_BYTES
        self.issues = []
        self.compatibility = 'unknown'
        self.regions = {}
        self.rows = []
        self.links = []
        self.catalog = self.features(CATALOG)
        for p in self.catalog:
            evidence.station_id('CATFIM', p['ahps_lid'])
            if p.get('usgs_gage') not in (None, ''):
                evidence.station_id('USGS', p['usgs_gage'])
            if not isinstance(p.get('states'), str):
                raise ValueError('Missing catalog coverage')
            states = p['states'].split(',')
            if not states or any(not re.fullmatch('[A-Z]{2}', s) for s in states):
                raise ValueError('Invalid catalog coverage')
            # Reject excessive source fields before constructing output records.
            if len(json.dumps(p, ensure_ascii=False, allow_nan=False).encode()) > evidence.MAX_RECORD_BYTES:
                raise data.EvidenceError('source_record_limit')
        for path in self.snapshot.manifest['files']:
            parts = path.split('/')
            if len(parts) != 4 or parts[0] != 'regions' or parts[2:] != ['relationships', 'inundation_scenarios.csv']:
                continue
            region = evidence.identifier(parts[1])
            if len(self.regions) >= MAX_REGIONS:
                raise data.EvidenceError('region_limit')
            self.regions[region] = {'index': path, 'state': 'unavailable'}
            try:
                rows = self.csv(path, SCENARIO_FIELDS)
                links = self.csv(f'regions/{region}/relationships/gauge_reach_links.csv', LINK_FIELDS)
                for row in rows:
                    for key in ('scenario_id', 'gauge_lid', 'fim_version', 'model_version'):
                        if row[key]:
                            evidence.identifier(row[key])
                    stage_number(row['stage'])
                if len(self.rows)+len(rows) > MAX_ROWS or len(self.links)+len(links) > MAX_ROWS:
                    raise data.EvidenceError('row_limit')
                self.rows.extend(dict(r, library_region=region) for r in rows)
                self.links.extend(dict(r, library_region=region) for r in links)
                self.regions[region]['state'] = 'available'
            except READ_ERRORS as exc:
                self.issues.append(region+':'+issue(exc))
        if not self.regions:
            self.issues.append('scenario_indexes_unavailable')

    def json(self, path):
        """Decode verified source bytes with per-file and aggregate expansion limits."""
        if path not in self.cache:
            raw = self.snapshot.artifact(path)
            limit = min(MAX_FEATURE_BYTES, self.expanded_remaining)
            if path.endswith('.gz'):
                with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
                    raw = stream.read(limit+1)
            if len(raw) > limit:
                raise data.EvidenceError('metadata_expansion_limit')
            self.expanded_remaining -= len(raw)
            self.snapshot.tick()
            self.cache[path] = json.loads(raw)
        self.snapshot.tick()
        return self.cache[path]

    def features(self, path):
        """Return source properties only; coordinate intersections do not establish identity."""
        document = self.json(path)
        if (not isinstance(document, dict) or document.get('type') != 'FeatureCollection'
                or not isinstance(document.get('features'), list) or len(document['features']) > MAX_ROWS):
            raise ValueError('Invalid feature collection')
        result = []
        for feature in document['features']:
            if not isinstance(feature, dict) or not isinstance(feature.get('properties'), dict):
                raise ValueError('Invalid source feature')
            result.append(feature['properties'])
        return result

    def csv(self, path, required):
        """Read complete bounded relationship tables; malformed rows cannot disappear silently."""
        raw = self.snapshot.artifact(path)
        if len(raw) > data.MAX_METADATA_BYTES:
            raise data.EvidenceError('relationship_size_limit')
        reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig'), newline=''), strict=True)
        fields = reader.fieldnames or []
        if len(fields) != len(set(fields)) or not set(required) <= set(fields):
            raise ValueError('Missing relationship fields')
        rows = []
        for row in reader:
            self.snapshot.tick()
            if len(rows) >= MAX_ROWS or None in row or any(row[k] is None for k in required):
                raise data.EvidenceError('invalid_or_excessive_relationship_rows')
            rows.append(row)
        return rows

    def check_dependencies(self):
        """Check Basin Plan pins once without erasing separately verified catalog evidence."""
        if hasattr(self, 'dependencies_checked'):
            return
        self.dependencies_checked = True
        try:
            self.compatibility = self.snapshot.check_basins()
            if self.compatibility != 'compatible':
                self.issues.append('basin_generation_incompatible')
        except READ_ERRORS as exc:
            self.issues.append('basin_dependency:'+issue(exc))

    def site_links(self, properties):
        """Join the recorded USGS key exactly; NOAA and CatFIM casing is never inferred."""
        number = properties.get('usgs_gage')
        return [r for r in self.links if number and r['usgs_id'] == number]

    def link_state(self, row):
        """Admit only the existing published/reviewed link statuses in the pinned network."""
        if row['network'] != self.snapshot.manifest.get('network'):
            return 'incompatible'
        try:
            evidence.station_id('NOAA', row['gauge_lid'])
            normalized = dict(station=evidence.station_id('USGS', row['usgs_id']), reach=row['reach_id'],
                              network=row['network'], status=row['status'], evidence=row['source_url'])
            return evidence.relationship([normalized], normalized['station'], row['reach_id'], row['network'])
        except ValueError:
            return 'unknown'

    def aliases(self, properties):
        """Expose source identity and only exact supported published station associations."""
        result = [evidence.station_id('CATFIM', properties['ahps_lid'])]
        if properties.get('usgs_gage'):
            result.append(evidence.station_id('USGS', properties['usgs_gage']))
        links = self.site_links(properties)
        if len(links) == 1 and self.link_state(links[0]) in ('reviewed', 'published_match'):
            result.append(evidence.station_id('NOAA', links[0]['gauge_lid']))
        return result

    def candidates(self, properties, library_region=None, gauge_lid=None):
        """Retain candidate scenarios without claiming that their links or data are eligible."""
        pairs = {(r['library_region'], r['gauge_lid']) for r in self.site_links(properties)}
        return [r for r in self.rows if (r['library_region'], r['gauge_lid']) in pairs
                and (library_region is None or r['library_region'] == library_region)
                and (gauge_lid is None or r['gauge_lid'] == gauge_lid)]

    def presence(self, relative):
        """Inspect a declared library's file identity without claiming checksum verification."""
        self.snapshot.tick()
        path = dataset_paths.checked_path(self.snapshot.directory, relative)
        try:
            value = path.stat()
        except FileNotFoundError:
            return path, None
        return path, (value.st_mode, value.st_size, value.st_mtime_ns, value.st_ctime_ns)

    def library_present(self, region):
        """Pin presence/absence of managed files; leftover undeclared files are not installed libraries."""
        relative = f'regions/{region}/inundation_scenarios.geojson.gz'
        if relative not in self.snapshot.manifest['files']:
            return False
        current = self.presence(relative)
        previous = self.library_presence.setdefault(relative, current)
        if previous != current:
            raise data.EvidenceError('generation_changed')
        return current[1] is not None and stat.S_ISREG(current[1][0])

    def finish(self):
        """Recheck both consumed bytes and presence facts before publishing discovery findings."""
        self.snapshot.finish()
        for relative, previous in self.library_presence.items():
            if self.presence(relative) != previous:
                raise data.EvidenceError('generation_changed')

    def site_record(self, properties, gauge_lid=None):
        """Keep provider facts and local findings separate, with no current-condition inference."""
        links = self.site_links(properties)
        if gauge_lid is not None:
            links = [r for r in links if r['gauge_lid'] == gauge_lid]
        rows = self.candidates(properties, gauge_lid=gauge_lid)
        mapping = {'yes': 'mapped', 'no': 'unmapped'}.get(properties.get('mapped'), 'unknown')
        link_state = 'missing' if not links else self.link_state(links[0]) if len(links) == 1 else 'ambiguous'
        states = properties['states'].split(',')
        geography = evidence.geography({'states': states}, link_state)
        indexes_complete = bool(self.regions) and all(r['state'] == 'available' for r in self.regions.values())
        local = 'installed' if rows else 'not_installed' if indexes_complete else 'unknown'
        if not rows and links and link_state not in ('reviewed', 'published_match'):
            local = 'unknown'
        if rows and any(not self.library_present(r['library_region']) for r in rows):
            local = 'unavailable'
        return dict(source=SOURCE, id=evidence.station_id('CATFIM', properties['ahps_lid']),
                    source_object_id=properties.get('oid'), aliases=self.aliases(properties),
                    name=properties.get('name'), states=states,
                    source_versions={k: properties.get(k) for k in ('fim_version', 'model_version')},
                    source_times={k: properties.get(k) for k in ('wrds_timestamp', 'nrldb_timestamp', 'nwis_timestamp')},
                    provider_report=dict(status=mapping, reported_at=None, reference=CATALOG,
                                         recorded_mapping=properties.get('mapped'),
                                         reason=properties.get('status'), date_qualification='mapping assessment time unknown'),
                    attributes=dict(catalog='listed', coverage='partial', provider_mapping=mapping,
                                    installation=local, integrity='passed', compatibility=self.compatibility,
                                    relationship=link_state, geography=geography,
                                    numerical_verification='not_assessed', predictive_validation='not_assessed'),
                    integrity_scope='catalog and consumed relationship indexes only',
                    library_integrity='unchecked', scenario_count=len(rows),
                    candidate_ids=[dict(id=r['scenario_id'], source=SOURCE, library_region=r['library_region'])
                                   for r in rows[:evidence.MAX_RESULTS]],
                    omitted_candidates=max(0, len(rows)-evidence.MAX_RESULTS),
                    scenario_eligibility='not_assessed',
                    qualification='Partial reference coverage; not current inundation or an all-clear.')

    def evaluate(self, row):
        """Keep a malformed scenario from erasing useful, separately verified site metadata."""
        try:
            return self._evaluate(row)
        except READ_ERRORS as exc:
            return dict(id=row['scenario_id'], source=SOURCE, library_region=row['library_region'],
                        eligible=False, reasons=['scenario_evidence:'+issue(exc)])

    def _evaluate(self, row):
        """Verify scenario provenance and return details only if W10-A permits reference use.

        Optional explicit vertical_reference dictionaries in source features must
        carry datum, zero, units and a source reference. Absent fields are never
        backfilled from another source. Current CatFIM fields may omit these.
        """
        self.check_dependencies()
        region, lid = row['library_region'], row['gauge_lid']
        references = dict(id=row['scenario_id'], source=SOURCE, library_region=region)
        reasons = []
        if sum(r['scenario_id'] == row['scenario_id'] and r['library_region'] == region for r in self.rows) != 1:
            return dict(**references, eligible=False, reasons=['scenario_identity:ambiguous'])
        links = [r for r in self.links if r['library_region'] == region and r['gauge_lid'] == lid]
        if len(links) != 1:
            return dict(**references, eligible=False, reasons=['relationship:ambiguous_or_missing'])
        link = links[0]
        sites = [p for p in self.catalog if p.get('usgs_gage') == link['usgs_id']]
        if len(sites) != 1:
            return dict(**references, eligible=False, reasons=['catalog_identity:ambiguous_or_missing'])
        site = sites[0]
        if any(site.get(key) not in (None, '', row[key]) for key in ('fim_version', 'model_version')):
            reasons.append('catalog_source_versions:conflicting')
        gauge_ref = scenario_ref = None
        source_rows = []
        try:
            gauge = self.json(source_path(row, 'raw/gauge_'+lid+'.json.gz'))
            if (not isinstance(gauge, dict) or gauge.get('lid') != lid
                    or gauge.get('usgsId') != link['usgs_id'] or gauge.get('reachId') != link['reach_id']):
                raise ValueError('Gauge identity conflict')
            datums = gauge.get('datums')
            if not isinstance(datums, dict) or not isinstance(datums.get('vertical'), dict):
                raise ValueError('Invalid gauge datum record')
            vertical = datums['vertical'].get('value', [])
            if isinstance(vertical, list) and len(vertical) == 1 and isinstance(vertical[0], dict):
                gauge_ref = dict(datum=vertical[0].get('abbrev'), zero=vertical[0].get('value'),
                                 units=vertical[0].get('units'))
            layer = row['source_layer']
            if not re.fullmatch('[0-9]+', layer) or row['source_url'] != SOURCE_URL+layer:
                raise ValueError('Unsupported scenario source')
            if row['source_stage_field'] not in ('stage', 'interval_stage'):
                raise ValueError('Unsupported stage parameter')
            object_ids = row['source_object_ids'].split(';')
            if len(object_ids) > evidence.MAX_RESULTS or len(set(object_ids)) != len(object_ids):
                raise ValueError('Ambiguous source object identities')
            features = self.features(source_path(row, 'inputs/catfim_'+layer+'.geojson.gz'))
            for object_id in object_ids:
                found = [p for p in features if p.get('oid') is not None and str(p['oid']) == object_id]
                if len(found) != 1:
                    raise ValueError('Source object missing or ambiguous')
                p = found[0]
                if (p.get('ahps_lid') != site['ahps_lid']
                        or stage_number(p.get(row['source_stage_field'])) != stage_number(row['stage'])
                        or p.get('stage_uni') != row['stage_units']
                        or p.get('fim_version') != row['fim_version'] or p.get('model_version') != row['model_version']):
                    raise ValueError('Source scenario metadata conflict')
                source_rows.append(p)
            recorded = [p.get('vertical_reference') for p in source_rows]
            if recorded and all(isinstance(r, dict) and r == recorded[0] for r in recorded):
                evidence.identifier(recorded[0].get('source_reference'))
                scenario_ref = recorded[0]
        except READ_ERRORS as exc:
            reasons.append('source_evidence:'+issue(exc))
        footprint = f'regions/{region}/inundation_scenarios.geojson.gz'
        integrity = 'unchecked'
        try:
            features = self.features(footprint)
            matches = [p for p in features if p.get('scenario_id') == row['scenario_id']]
            if len(matches) != 1:
                raise ValueError('Footprint identity missing or ambiguous')
            p = matches[0]
            if p.get('source_prefix', '') != row.get('source_prefix', ''):
                raise ValueError('Footprint source prefix mismatch')
            source_features = self.json(footprint)['features']
            geometry = next(f.get('geometry') for f in source_features if f['properties'] is p)
            if (not isinstance(geometry, dict) or geometry.get('type') not in ('Polygon', 'MultiPolygon')
                    or not isinstance(geometry.get('coordinates'), list) or not geometry['coordinates']):
                raise ValueError('Missing footprint geometry')
            for key in SCENARIO_FIELDS:
                if key == 'stage':
                    if stage_number(p.get(key)) != stage_number(row[key]):
                        raise ValueError('Footprint stage mismatch')
                elif str(p.get(key, '')) != row[key]:
                    raise ValueError('Footprint source metadata mismatch')
            integrity = 'passed'
        except READ_ERRORS as exc:
            integrity = 'failed'
            reasons.append('footprint:'+issue(exc))
        mapping = {'yes': 'mapped', 'no': 'unmapped'}.get(site.get('mapped'), 'unknown')
        state = self.link_state(link)
        # Cross-border relevance needs an explicit drainage review in the source
        # link; station/reach identity alone does not supply that review.
        drainage_review = link.get('drainage_review')
        geography = evidence.geography({'states': site['states'].split(',')}, state, drainage_review)
        attrs = dict(catalog='listed', coverage='partial', provider_mapping=mapping, installation='installed',
                     integrity=integrity, compatibility=self.compatibility, relationship=state,
                     geography=geography, parameter='applicable', observation='not_applicable',
                     vertical_reference=evidence.vertical_reference(gauge_ref, scenario_ref))
        provenance = dict(catalog_reference=CATALOG, relationship_reference=link['source_url'],
                          integrity_reference=footprint, compatibility_reference='basin_source')
        if drainage_review:
            provenance['drainage_review'] = drainage_review
        value = evidence.record(row['scenario_id'], 'published_hypothetical_scenario', source=SOURCE,
            generation=self.snapshot.manifest['generation'], vintage=self.snapshot.manifest.get('created_at_utc'),
            extent=dict(id=region, states=site['states'].split(',')), attributes=attrs, provenance=provenance,
            provider_report=dict(status=mapping, reference=CATALOG, reported_at=None, retrieved_at=None,
                                 reason=site.get('status')),
            scenario=dict(id=row['scenario_id'], gauge_id=evidence.station_id('NOAA', lid),
                          stage=float(stage_number(row['stage'])), units=row['stage_units'],
                          source_version=row['fim_version'], model_version=row['model_version'],
                          gauge_reference=gauge_ref, scenario_reference=scenario_ref))
        decision = evidence.assess(value)
        reasons += decision['reasons']
        if row['evidence_class'] != 'experimental_static_stage_scenario' or row['event_valid_time']:
            reasons.append('unsupported_evidence_class_or_event_time')
        if not reasons:
            from . import flood_geometry
            try:
                flood_geometry.selected_geometry(self, row)
            except READ_ERRORS as exc:
                reasons.append('geometry:'+issue(exc))
        result = dict(**references, eligible=not reasons, reasons=list(dict.fromkeys(reasons)),
                      qualifications=[decision['qualification'], 'Partial coverage; predictive validation not assessed.'])
        if result['eligible']:
            result.update(evidence=value, recorded_stage=row['stage'], category=row.get('category'),
                          source_prefix=row.get('source_prefix', ''),
                          depth_status=row['depth_status'], reach_id=link['reach_id'], network=link['network'],
                          footprint=dict(path=footprint, scenario_id=row['scenario_id'],
                                         **self.snapshot.manifest['files'][footprint]),
                          source_objects=row['source_object_ids'], source_url=row['source_url'])
        return result
