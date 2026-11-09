"""Maintenance-only reviewed library acquisition, admission and derived intersections.

Runtime modules never import this module. These functions do not activate a
generation or acquire downstream dependencies. Acquisition needs a reviewed batch.
"""
import json
import gzip
import io
import math
import re

from . import archive
from data.basin_plans.organize import CALWATER_LEVELS
from meshcore_mqtt_service.scripts import flood_catalog, flood_geometry
from meshcore_mqtt_service.scripts.flood_reference_data import EvidenceError

CATFIM = flood_catalog.SOURCE_URL.rstrip('/')
SCENARIO_LAYERS = (2, 3, 5, 6, 8, 9, 11, 12, 13)
MAX_SOURCE_RECORDS = 16384


def verify_basin_subset(reader, entry, subset):
    """Compare copied features with the checksum-pinned Basin Plan source collection.

    A provenance record describes a copy; it cannot prove that the geometry or
    properties survived unchanged. Verification shares the read/decompression
    budgets and file-replacement checks of the enclosing flood transaction.
    """
    basin = reader.snapshot.basin
    if (entry.get('kind') != 'spatial' or type(entry.get('record_count')) is not int
            or not 0 <= entry['record_count'] <= MAX_SOURCE_RECORDS):
        raise EvidenceError('basin_source_membership_invalid_or_excessive')
    path = basin.path(basin.source, entry['path'])
    raw = reader.snapshot.checked(path, entry)
    limit = min(flood_catalog.MAX_FEATURE_BYTES, reader.expanded_remaining)
    if entry['path'].endswith('.gz'):
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
            raw = stream.read(limit+1)
    if len(raw) > limit:
        raise EvidenceError('basin_source_expansion_limit')
    reader.expanded_remaining -= len(raw)
    reader.snapshot.tick()
    document = json.loads(raw)
    if not isinstance(document, dict):
        raise EvidenceError('basin_source_document_invalid')
    features = document.get('features')
    if (document.get('type') != 'FeatureCollection' or not isinstance(features, list)
            or len(features) != entry['record_count'] or len(features) > MAX_SOURCE_RECORDS):
        raise EvidenceError('basin_source_membership_invalid_or_excessive')
    if document.get('crs') != subset.get('crs'):
        raise EvidenceError('basin_source_crs_conflict')
    original = {}
    for feature in features:
        identifier = feature['properties'][entry['object_id_field']]
        if type(identifier) not in (str, int) or str(identifier).strip() == '':
            raise EvidenceError('basin_source_identity_invalid')
        key = (type(identifier), identifier)
        if key in original:
            raise EvidenceError('basin_source_identity_conflict')
        original[key] = feature
    for feature in subset['features']:
        identifier = feature['properties'][entry['object_id_field']]
        if (type(identifier) not in (str, int) or str(identifier).strip() == ''
                or original.get((type(identifier), identifier)) != feature):
            raise EvidenceError('basin_source_feature_mismatch')
        reader.snapshot.tick()
    return dict(path=entry['path'], sha256=entry['sha256'], byte_count=entry['byte_count'])


def acquire_review_batch(stage, *, catalog_id, catalog_lid, gauge_lid, usgs_id, budget,
                         fim_version, model_version):
    """Archive one explicitly reviewed CatFIM identity; return evidence, not admission.

    Identifiers must be supplied independently in their recorded spelling. No
    case conversion, geographic clipping, routing download or pointer write occurs.
    Version changes and absent datum associations remain review findings.
    """
    if (type(catalog_id) is not int or catalog_id < 0
            or not isinstance(budget, archive.AcquisitionBudget)
            or not re.fullmatch(r'[a-z0-9]{5}', catalog_lid)
            or not re.fullmatch(r'[A-Z0-9]{5}', gauge_lid)
            or not re.fullmatch(r'[0-9]{8,15}', usgs_id)
            or not isinstance(fim_version, str) or not fim_version
            or not isinstance(model_version, str) or not model_version):
        raise ValueError('Invalid reviewed acquisition identity or budget')
    service = archive.fetch(stage, 'catfim_service', CATFIM, {'f': 'json'}, budget=budget)
    ids = [r['id'] for r in service['layers'] if r.get('geometryType') == 'esriGeometryPolygon']
    if len(ids) != len(set(ids)) or set(ids) != set(SCENARIO_LAYERS):
        raise ValueError('Provider layer inventory changed; batch review required')
    sites = archive.arcgis(stage, 'candidate_sites', CATFIM+'/0', f'oid = {catalog_id}', budget=budget)
    if len(sites['features']) != 1:
        raise ValueError('Candidate site identity missing or ambiguous')
    site = sites['features'][0]['properties']
    if (site.get('oid') != catalog_id or site.get('ahps_lid') != catalog_lid
            or site.get('usgs_gage') != usgs_id):
        raise ValueError('Candidate catalog identity changed')
    if site.get('fim_version') != fim_version or site.get('model_version') != model_version:
        raise ValueError('Candidate source versions changed; batch review required')
    for layer in SCENARIO_LAYERS:
        document = archive.arcgis(stage, f'catfim_{layer}', CATFIM+f'/{layer}',
                                 f"ahps_lid = '{catalog_lid}'", budget=budget)
        for feature in document['features']:
            properties = feature['properties']
            if (properties.get('ahps_lid') != catalog_lid or properties.get('fim_version') != fim_version
                    or properties.get('model_version') != model_version):
                raise ValueError('Candidate footprint identity or version changed')
    gauge = archive.fetch(stage, 'gauge_'+gauge_lid,
                          'https://api.water.noaa.gov/nwps/v1/gauges/'+gauge_lid, budget=budget)
    station = archive.fetch(stage, 'nldi_'+gauge_lid,
        'https://api.water.usgs.gov/nldi/linked-data/nwissite/USGS-'+usgs_id, {'f': 'json'}, budget=budget)
    if gauge.get('lid') != gauge_lid or gauge.get('usgsId') != usgs_id:
        raise ValueError('Candidate gauge identity changed')
    records = station.get('features', [])
    if len(records) != 1 or records[0]['properties'].get('identifier') != 'USGS-'+usgs_id:
        raise ValueError('Candidate NLDI identity changed')
    return dict(status='unreviewed', catalog_id=catalog_id, catalog_lid=catalog_lid,
                gauge_lid=gauge_lid, usgs_id=usgs_id, fim_version=site.get('fim_version'),
                model_version=site.get('model_version'), activation=False,
                qualification='Acquired evidence only; datum, link, geometry and dependency review required.')


def admission(config):
    """Review every indexed scenario independently, preserving failed-library findings.

    Whole-generation integrity is checked separately from per-scenario eligibility.
    The result is a bounded machine-readable assessment, never an activation token.
    """
    reader = flood_catalog.Catalog(config)
    reader.check_dependencies()
    groups = {}
    for row in reader.rows:
        key = (row['library_region'], row['gauge_lid'], row['fim_version'], row['model_version'], row.get('source_prefix', ''))
        group = groups.setdefault(key, dict(library_region=key[0], gauge_id='NOAA-'+key[1],
            fim_version=key[2], model_version=key[3], source_prefix=key[4], scenarios=[]))
        outcome = reader.evaluate(row)
        group['scenarios'].append(dict(id=outcome['id'], eligible=outcome['eligible'], reasons=outcome['reasons']))
    for group in groups.values():
        count = sum(r['eligible'] for r in group['scenarios'])
        group['status'] = 'eligible' if count == len(group['scenarios']) else 'partial' if count else 'ineligible'
    reader.snapshot.verify_all()
    reader.finish()
    result = dict(generation=reader.snapshot.manifest['generation'], libraries=list(groups.values()),
                  unavailable_indexes=[k for k,v in reader.regions.items() if v['state'] != 'available'],
                  issues=reader.issues, activation=False, predictive_validation='not_assessed')
    if len(json.dumps(result, allow_nan=False).encode()) > 128*1024:
        raise EvidenceError('admission_result_limit')
    return result


def retain_candidate(root, stage, identifier, details, previous_pointer, validate_candidate):
    """Seal a validated candidate without activation or loss of previous artifacts.

    The caller holds the existing build lock. Original generation files must be
    retained byte-for-byte. Replacing shared artifacts requires a separately
    reviewed migration; this conservative path cannot silently reduce coverage.
    Validation must include semantic admission and dependency compatibility.
    """
    if archive.read_json(root/'static.json') != previous_pointer:
        raise ValueError('Active generation changed')
    _, old_manifest = archive.open_generation(root, pointer=previous_pointer)
    if details.get('basin_source') != old_manifest.get('basin_source'):
        raise ValueError('Candidate dependency pin changed')
    reserved = {'schema_version', 'generation', 'kind', 'complete', 'created_at_utc', 'files'}
    retained_details = {key: value for key, value in old_manifest.items() if key not in reserved}
    if any(key in retained_details and retained_details[key] != value for key, value in details.items()):
        raise ValueError('Candidate changed retained generation metadata')
    retained_details.update(details)
    for relative, expected in old_manifest['files'].items():
        if archive.digest(archive.safe_path(stage, relative)) != expected:
            raise ValueError('Candidate changed or removed retained coverage')

    def validate(directory, manifest):
        """Run semantic checks before sealing, then recheck the active pin."""
        validate_candidate(directory, manifest)
        if archive.read_json(root/'static.json') != previous_pointer:
            raise ValueError('Active generation changed')

    return archive.publish(root, stage, identifier, 'static', retained_details, activate=False, validator=validate)


def derive_intersections(config, scenario_id, library_region):
    """Derive six independent CalWater overlaps from pinned originals, without repair.

    Returns machine-readable rows and GeoJSON for the existing generation builder
    to archive. Coverage is the installed subset, not statewide basin completeness.
    Nested areas are never summed and no downstream clipping is performed.
    """
    import pyproj
    import shapely
    from pyproj import Transformer
    from shapely.geometry import mapping
    from shapely.ops import transform
    from shapely.errors import GEOSException
    reader = flood_catalog.Catalog(config)
    rows = [r for r in reader.rows if r['scenario_id'] == scenario_id and r['library_region'] == library_region]
    if len(rows) != 1 or not reader.evaluate(rows[0])['eligible']:
        raise EvidenceError('intersection_scenario_ineligible_or_ambiguous')
    budget = flood_geometry.Budget(reader.snapshot.tick)
    footprint = flood_geometry.selected_geometry(reader, rows[0], budget)
    if not (-125 <= footprint.bounds[0] <= footprint.bounds[2] <= -113
            and 32 <= footprint.bounds[1] <= footprint.bounds[3] <= 43):
        raise EvidenceError('intersection_metric_crs_extent_unsupported')
    forward = Transformer.from_crs('OGC:CRS84', 'EPSG:3310', always_xy=True).transform
    inverse = Transformer.from_crs('EPSG:3310', 'OGC:CRS84', always_xy=True).transform
    footprint = transform(forward, footprint)
    provenance = reader.json(flood_catalog.source_path(rows[0], 'inputs/basin_provenance.json'))
    if provenance.get('source_pointer') != reader.snapshot.manifest['basin_source']:
        raise EvidenceError('intersection_dependency_mismatch')
    results, features, inputs, originals = [], [], {}, {}
    try:
        for name, (level, title) in CALWATER_LEVELS.items():
            sources = [p for p in provenance['datasets'] if p['name'] == name]
            if len(sources) != 1:
                raise EvidenceError('intersection_calwater_level_missing_or_ambiguous')
            source = sources[0]
            entry = reader.snapshot.basin.entries.get(source['dataset_key'])
            if (entry is None or entry.get('name') != name
                    or entry.get('sha256') != source.get('source_sha256')
                    or entry.get('source_url') != source.get('source_url')
                    or entry.get('object_id_field') != source.get('object_id_field')
                    or entry.get('record_count') != source.get('source_record_count')):
                raise EvidenceError('intersection_source_provenance_conflict')
            if (source['snapshot_id'] != provenance['source_pointer']['snapshot_id']
                    or source['path'] != 'inputs/'+name+'.geojson.gz'):
                raise EvidenceError('intersection_source_pin_conflict')
            source_path = flood_catalog.source_path(rows[0], source['path'])
            document = reader.json(source_path)
            reader.features(source_path)
            if len(document['features']) != source.get('selected_count'):
                raise EvidenceError('intersection_incomplete_subset')
            originals[source['dataset_key']] = verify_basin_subset(reader, entry, document)
            inputs[source_path] = reader.snapshot.manifest['files'][source_path]
            seen = set()
            for feature in document['features']:
                oid = feature['properties'][source['object_id_field']]
                if type(oid) not in (str, int) or str(oid).strip() == '' or str(oid) in seen:
                    raise EvidenceError('intersection_basin_identity_conflict')
                seen.add(str(oid))
                boundary = transform(forward, flood_geometry.polygon(document, feature, budget))
                budget.operation()
                overlap = footprint.intersection(boundary)
                if overlap.is_empty or overlap.area == 0:
                    continue
                if not all(math.isfinite(v) and v > 0 for v in (overlap.area, boundary.area)):
                    raise EvidenceError('intersection_invalid_area')
                row = dict(scenario_id=scenario_id, library_region=library_region,
                    basin_id=source['dataset_key']+':'+str(oid), calwater_level=level,
                    calwater_title=title, affected_area_m2=overlap.area, basin_area_m2=boundary.area,
                    basin_fraction=overlap.area/boundary.area)
                results.append(row)
                features.append(dict(type='Feature', geometry=mapping(transform(inverse, overlap)), properties=row))
            budget.tick()
    except GEOSException:
        raise EvidenceError('intersection_geometry_failed') from None
    reader.finish()
    result = dict(generation=reader.snapshot.manifest['generation'], basin_source=provenance['source_pointer'],
        inputs=inputs, basin_originals=originals, scenario_source={p:reader.snapshot.manifest['files'][p] for p in (
            f'regions/{library_region}/inundation_scenarios.geojson.gz',
            flood_catalog.source_path(rows[0], 'inputs/catfim_'+rows[0]['source_layer']+'.geojson.gz'))},
        method='EPSG:3310 area intersection; no geometry repair; independent hierarchy levels',
        software=dict(shapely=shapely.__version__, pyproj=pyproj.__version__, proj=pyproj.proj_version_str),
        coverage='Installed CalWater subsets only; incomplete coverage remains unassessed',
        qualification='Reporting areas, not computational catchments, storage volumes or hydraulic predictions',
        rows=results, geojson=dict(type='FeatureCollection', features=features))
    if len(json.dumps(result, allow_nan=False).encode()) > 8*1024*1024:
        raise EvidenceError('intersection_output_limit')
    return result
