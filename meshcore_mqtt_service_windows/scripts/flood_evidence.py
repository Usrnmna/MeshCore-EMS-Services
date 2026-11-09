"""W10-A evidence contracts; no scenario selection, forecasts, or hydraulic calculations."""
from copy import deepcopy
from datetime import datetime, timezone
import json
import math
import os
import re

from .basin_plan_data import LEVELS, LEVEL_NAMES
from .response_text import MESSAGE_BYTES

MAX_IDENTIFIER_BYTES = 160
MAX_RESULTS = 20
MAX_RECORD_BYTES = 32768
EVIDENCE_CLASSES = (
    'observation', 'measured_change', 'observed_threshold_margin',
    'published_hypothetical_scenario', 'source_forecast', 'local_model_estimate',
    'validated_model_result', 'official_watch', 'official_warning', 'static_flood_hazard',
)
# These attributes are independent; no ordinal state or combined safety score exists.
STATES = {
    'catalog': ('unknown', 'listed', 'not_listed'),
    'coverage': ('unknown', 'complete', 'partial', 'unavailable'),
    'provider_mapping': ('unknown', 'mapped', 'unmapped', 'unavailable'),
    'installation': ('unknown', 'installed', 'not_installed', 'removed', 'unavailable'),
    'integrity': ('unchecked', 'passed', 'failed', 'partial', 'unavailable'),
    'compatibility': ('unknown', 'compatible', 'incompatible'),
    'relationship': ('unknown', 'reviewed', 'published_match', 'missing', 'ambiguous', 'conflicting', 'unsupported', 'incompatible'),
    'geography': ('not_assessed', 'california', 'cross_border_reviewed', 'outside_scope', 'unsupported'),
    'parameter': ('unknown', 'applicable', 'unsupported', 'incompatible'),
    'vertical_reference': ('unknown', 'compatible', 'missing', 'incompatible'),
    'observation': ('unknown', 'fresh', 'stale', 'unavailable', 'invalid', 'not_applicable'),
    'numerical_verification': ('not_assessed', 'passed', 'failed'),
    'predictive_validation': ('not_assessed', 'passed', 'failed', 'outside_scope'),
    'acquisition': ('not_checked', 'succeeded', 'failed'),
}
STATUS_MEANINGS = {
    'unknown': 'Evidence is insufficient to establish this attribute.',
    'unsupported': 'The source or implemented method does not support the requested use.',
    'unavailable': 'Required evidence cannot currently be read or obtained.',
    'not_installed': 'No local artifact is present; provider availability is a separate fact.',
    'removed': 'Managed dataset selection explicitly disables fallback to older copies.',
    'not_assessed': 'No assessment for the stated area and purpose has been established.',
    'partial': 'Only the explicitly identified subset was checked or is usable.',
    'failed': 'The specified check failed; this does not redefine unrelated attributes.',
    'incompatible': 'Inputs cannot be combined under the required generation or semantic contract.',
}


def identifier(value):
    """Preserve literal identities, including namespaces and zeroes; never coerce numbers."""
    if (not isinstance(value, str) or not value or value != value.strip()
            or len(value.encode('utf-8')) > MAX_IDENTIFIER_BYTES
            or any(not c.isprintable() or c in '|' for c in value)):
        raise ValueError('Invalid or excessive source identifier')
    return value


def station_id(agency, number):
    """Construct W07's exact agency-qualified identity from recorded string fields."""
    agency, number = identifier(agency), identifier(number)
    if not re.fullmatch(r'[A-Za-z0-9]+', agency) or not re.fullmatch(r'[A-Za-z0-9-]+', number):
        raise ValueError('Invalid station namespace or number')
    return identifier(agency+'-'+number)


def instant(value):
    """Require aware source timestamps; receipt time is never an observation substitute."""
    if not isinstance(value, str):
        raise ValueError('Missing source timestamp')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Naive source timestamp')
    return parsed.astimezone(timezone.utc)


def observation_state(observed_at, now, max_age):
    """Classify freshness from the observation endpoint, without measuring a trend."""
    if not all(type(v) in (int, float) and math.isfinite(v) for v in (now, max_age)) or max_age <= 0:
        raise ValueError('Invalid observation clock or age limit')
    if observed_at is None:
        return 'unavailable'
    try:
        age = now-instant(observed_at).timestamp()
    except (ValueError, TypeError, OverflowError):
        return 'invalid'
    return 'invalid' if age < 0 else 'stale' if age > max_age else 'fresh'


def record(source_id, evidence_class, *, source, generation, extent, vintage=None, attributes=None,
           provenance=None, scenario=None, validation=None, provider_report=None):
    """Create a bounded, source-qualified record without deriving one state from another.

    Provenance contains supporting source IDs/review references, not guessed links.
    Positive numerical/predictive claims require a scope-bound assessment record.
    Static vintage is retained independently of observation freshness.
    """
    value = dict(id=identifier(source_id), evidence_class=evidence_class,
                 source=identifier(source), generation=identifier(generation), extent=deepcopy(extent),
                 vintage=vintage, attributes={k: v[0] for k, v in STATES.items()},
                 provenance=deepcopy(provenance or {}), scenario=deepcopy(scenario),
                 validation=deepcopy(validation or {}), provider_report=deepcopy(provider_report))
    if attributes:
        value['attributes'].update(attributes)
    validate(value)
    return value


def validate(value):
    """Reject ambiguous contracts before eligibility or radio output is computed."""
    required = {'id', 'source', 'generation', 'evidence_class', 'vintage', 'extent',
                'attributes', 'provenance', 'validation'}
    if not isinstance(value, dict) or not required <= value.keys():
        raise ValueError('Incomplete evidence record')
    for key in ('id', 'source', 'generation'):
        identifier(value[key])
    if value['evidence_class'] not in EVIDENCE_CLASSES:
        raise ValueError('Unsupported evidence class')
    if value['vintage'] is not None:
        instant(value['vintage'])
    extent = value['extent']
    if not isinstance(extent, dict) or not isinstance(extent.get('states'), list):
        raise ValueError('Geographic extent must be explicit')
    identifier(extent.get('id'))
    if len(extent['states']) > 10 or any(not isinstance(s, str) or not re.fullmatch('[A-Z]{2}', s) for s in extent['states']):
        raise ValueError('Invalid geographic state identifiers')
    attributes = value['attributes']
    if (not isinstance(attributes, dict) or set(attributes) != set(STATES)
            or any(attributes[k] not in STATES[k] for k in STATES)):
        raise ValueError('Unsupported evidence attribute')
    provenance = value['provenance']
    if not isinstance(provenance, dict) or not isinstance(value['validation'], dict):
        raise ValueError('Invalid provenance')
    for key, reference in provenance.items():
        identifier(key)
        identifier(reference)
    report = value.get('provider_report')
    if attributes['provider_mapping'] in ('mapped', 'unmapped') and not isinstance(report, dict):
        raise ValueError('Provider mapping claim requires recorded source evidence')
    if report is not None:
        if not isinstance(report, dict) or report.get('status') != attributes['provider_mapping']:
            raise ValueError('Provider mapping evidence conflict')
        identifier(report.get('reference'))
        # A null source time explicitly preserves undated evidence. Retrieval time
        # is stored separately and cannot manufacture a provider assessment date.
        for key in ('reported_at', 'retrieved_at'):
            if key not in report:
                raise ValueError('Provider evidence time must be explicit, including unknown')
            if report[key] is not None:
                instant(report[key])
        reason = report.get('reason')
        if reason is not None and (not isinstance(reason, str) or len(reason.encode()) > 2048):
            raise ValueError('Provider qualification exceeds bound')
    if value['evidence_class'] == 'validated_model_result' and attributes['predictive_validation'] != 'passed':
        raise ValueError('Validated model class requires scoped validation')
    for attribute in ('numerical_verification', 'predictive_validation'):
        if attributes[attribute] == 'passed':
            assessment = value['validation'].get(attribute)
            if not isinstance(assessment, dict):
                raise ValueError('Validation claim requires scoped evidence')
            for key in ('reference', 'method', 'purpose', 'source', 'evidence_id', 'generation', 'extent_id'):
                identifier(assessment.get(key))
            instant(assessment.get('assessed_at'))
            if (assessment['generation'] != value['generation'] or assessment['extent_id'] != extent['id']
                    or assessment['source'] != value['source'] or assessment['evidence_id'] != value['id']):
                raise ValueError('Validation scope mismatch')
    if len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode()) > MAX_RECORD_BYTES:
        raise ValueError('Evidence record exceeds bound')
    return value


def geography(extent, relationship, review_reference=None):
    """Classify stated coverage; cross-border applicability requires reviewed drainage evidence."""
    states = extent.get('states', [])
    if states == ['CA']:
        return 'california'
    if 'CA' in states and relationship in ('reviewed', 'published_match') and review_reference:
        identifier(review_reference)
        return 'cross_border_reviewed'
    return 'not_assessed' if states else 'unsupported'


def relationship(rows, station, reach, network):
    """Require one exact supported station/reach association, not endpoint existence.

    Normalized rows retain explicit station, reach, network, status, and evidence
    references. Conflicting targets for the station prevent arbitrary selection.
    """
    for value in (station, reach, network):
        identifier(value)
    if not isinstance(rows, list) or len(rows) > MAX_RESULTS:
        raise ValueError('Relationship count exceeds bound')
    matches = [row for row in rows if row.get('station') == station]
    if not matches:
        return 'missing'
    if len(matches) != 1:
        return 'ambiguous' if all(r == matches[0] for r in matches) else 'conflicting'
    row = matches[0]
    if row.get('network') != network:
        return 'incompatible'
    if row.get('reach') != reach:
        return 'conflicting'
    status = {'published_identifier_match': 'published_match', 'reviewed': 'reviewed'}.get(row.get('status'))
    if status is None:
        return 'unsupported'
    try:
        identifier(row['evidence'])
    except (KeyError, ValueError):
        return 'unknown'
    return status


def vertical_reference(gauge, scenario):
    """Compare explicitly recorded references exactly, without conversions or inferred gauge zeroes."""
    required = ('datum', 'zero', 'units')
    for record in (gauge, scenario):
        if not isinstance(record, dict) or any(record.get(k) is None for k in required):
            return 'missing'
        if (not isinstance(record['datum'], str)
                or record['datum'].strip().casefold() in ('', 'unk', 'unknown', 'nan', 'n/a', 'null', 'none')
                or type(record['zero']) not in (int, float) or not math.isfinite(record['zero'])):
            return 'missing'
        if record['units'] not in ('ft', 'FT', 'm'):
            return 'incompatible'
    return 'compatible' if all(gauge[k] == scenario[k] for k in required) else 'incompatible'


def assess(value):
    """Return separate discovery and static-reference decisions with complete reasons.

    This does not select scenarios, certify models, or authorize current-event use.
    Every future evidence class remains distinct and is unsupported by this slice.
    """
    validate(value)
    a = value['attributes']
    discovery = a['catalog'] == 'listed' and bool(value['provenance'].get('catalog_reference'))
    reasons = []
    required = dict(installation=('installed',), integrity=('passed',), compatibility=('compatible',),
                    relationship=('reviewed', 'published_match'), geography=('california', 'cross_border_reviewed'),
                    parameter=('applicable',), vertical_reference=('compatible',))
    if value['evidence_class'] != 'published_hypothetical_scenario':
        reasons.append('evidence_class:unsupported_for_static_reference')
    for key, allowed in required.items():
        if a[key] not in allowed:
            reasons.append(key+':'+a[key])
    for key in ('relationship_reference', 'integrity_reference', 'compatibility_reference'):
        if not value['provenance'].get(key):
            reasons.append(key+':missing')
    if a['geography'] == 'california' and value['extent']['states'] != ['CA']:
        reasons.append('geography:scope_conflict')
    if a['geography'] == 'cross_border_reviewed' and ('CA' not in value['extent']['states']
            or not value['provenance'].get('drainage_review')):
        reasons.append('geography:review_missing')
    scenario = value.get('scenario')
    if not isinstance(scenario, dict):
        reasons.append('scenario_metadata:missing')
    else:
        try:
            for key in ('id', 'gauge_id', 'source_version', 'model_version'):
                identifier(scenario[key])
            stage = scenario['stage']
            if type(stage) not in (int, float) or not math.isfinite(stage) or scenario['units'] not in ('ft', 'FT', 'm'):
                raise ValueError('Unsupported stage')
            if scenario['id'] != value['id']:
                raise ValueError('Scenario identity conflict')
            datum_state = vertical_reference(scenario.get('gauge_reference'), scenario.get('scenario_reference'))
            if datum_state != 'compatible':
                reasons.append('scenario_vertical_reference:'+datum_state)
            else:
                unit = {'ft': 'ft', 'FT': 'ft', 'm': 'm'}
                if unit[scenario['units']] != unit[scenario['scenario_reference']['units']]:
                    reasons.append('scenario_stage_units:incompatible')
        except (ValueError, TypeError, KeyError):
            reasons.append('scenario_metadata:missing_or_conflicting')
    contradictions = []
    if a['provider_mapping'] == 'unmapped' and a['installation'] == 'installed':
        contradictions.append('provider_unmapped_with_installed_library')
        reasons.append('provider_mapping:conflicting')
    if a['catalog'] == 'not_listed' and a['installation'] == 'installed':
        contradictions.append('installed_library_not_in_selected_catalog')
    return dict(discovery=discovery, static_reference=not reasons, reasons=reasons,
                contradictions=contradictions, current_inundation='not_assessed',
                provider_evidence_time='dated' if (value.get('provider_report') or {}).get('reported_at') else 'unknown',
                qualification='Hypothetical reference only; not current flooding or an all-clear.')


def calwater(level, source_id, generation):
    """Retain all six reporting levels without implying flow, storage, or overflow."""
    if level not in LEVELS:
        raise ValueError('Not a CalWater hierarchy level')
    return dict(level=level, name=LEVEL_NAMES[LEVELS.index(level)], id=identifier(source_id),
                generation=identifier(generation), meaning='reporting boundary; not hydraulic connectivity')


def summaries(records):
    """Format bounded evidence summaries; never truncate identity or mandatory qualifiers."""
    if not isinstance(records, list) or not 1 <= len(records) <= MAX_RESULTS:
        raise ValueError('Evidence summary count must be 1..20')
    identities = [(r['source'], r['generation'], r['id']) for r in records]
    if len(set(identities)) != len(identities):
        raise ValueError('Duplicate or ambiguous evidence identity')
    fields = []
    for row in records:
        decision = assess(row)
        state = 'eligible hypothetical reference' if decision['static_reference'] else 'reference ineligible: '+','.join(decision['reasons'])
        attributes = row['attributes']
        validation = {'not_assessed': 'not validated', 'failed': 'validation failed',
                      'outside_scope': 'validation out of scope', 'passed': 'validation scoped'}
        qualifications = 'coverage '+attributes['coverage']+'; '+validation[attributes['predictive_validation']]
        if attributes['numerical_verification'] == 'failed':
            qualifications += '; numerical check failed'
        fields.append(row['source']+':'+row['id']+'@'+row['generation']+' '+state+'; '+qualifications)
    text = '; '.join(fields)+'; not current flooding; not all-clear.'
    budget = MESSAGE_BYTES-len(('@'+os.environ.get('MESHCORE_SENDER', 'Reader')+' ').encode())
    for candidate in (text, 'Flood evidence details withheld; narrow selection. Not all-clear.', 'Details withheld; not all-clear.'):
        if len(candidate.encode()) <= budget:
            return candidate
    return ''
