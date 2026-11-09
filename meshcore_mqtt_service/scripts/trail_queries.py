"""Recorded trail endpoint choices and AND-filtered EBMUD proximity queries."""
import math
import os

if __package__:
    from .gis_data import find_by_name, normalize_name
    from .response_text import MESSAGE_BYTES, compact_fields, short_label
else:
    from gis_data import find_by_name, normalize_name
    from response_text import MESSAGE_BYTES, compact_fields, short_label

SHADE_VALUES = {'equal parts shade and sun', 'mostly shade', 'full shade'}


def reply_budget():
    """Reserve the requesting sender's UTF-8 tag before formatting essential text."""
    return MESSAGE_BYTES - len(('@' + os.environ.get('MESHCORE_SENDER', 'Reader') + ' ').encode())


def help_text(topic):
    """Expose W06 forms and exact shade eligibility without dataset access."""
    topics = {
        'endpoints': '!trail NAME start/end [id ID]; mapped only; access unknown',
        'find': '!trail find FILTERS near LAT LON [MILES]; help filters',
        'filters': 'AND filters: dogs horses bikes shade; help shade',
        'shade': 'Shade: Equal Parts Shade and Sun, Mostly Shade, Full Shade',
    }
    if topic not in topics:
        raise ValueError('Use !trail help endpoints/filters/find/shade.')
    return compact_fields(topics[topic])


def nearest_groups(groups, location, spatial, settings):
    """Return radius matches or closest ties without selecting by arbitrary name."""
    point = spatial.point(*location[:2])
    radius = location[2] if len(location) == 3 else None
    if radius is not None and radius > settings['maximum_radius_miles']:
        raise ValueError(f'Radius must not exceed {settings["maximum_radius_miles"]:g} miles.')
    # Legacy GIS requests without a radius select the closest within projection
    # coverage; they are not implicitly restricted to the configured radius.
    for group in groups:
        if any(record['geometry'] is None for record in group):
            raise ValueError('Eligible trail geometry incomplete; nearest unknown.')
    found = spatial.nearby(groups, point, radius if radius is not None else float('inf'))
    if radius is not None or not found:
        return found
    return [(group, distance) for group, distance in found
            if math.isclose(distance, found[0][1], rel_tol=0, abs_tol=0.01 / 1609.344)]


def ambiguous_trails(groups):
    """Return bounded names for an unresolved trail identity."""
    return compact_fields('Multiple trails; use a full name.', [group[0]['name'] for group in groups])


def endpoint_reply(mode, value, attribute, groups, snapshot, spatial, settings):
    """Use recorded roles and endpoint OBJECTID_1, never line-vertex order.

    OBJECTID is a trail association and is not a unique endpoint identifier.
    Supplementary start/end descriptions do not establish point coordinates.
    """
    role, selected = (attribute[1], attribute[2]) if isinstance(attribute, tuple) else (attribute, None)
    if mode in {'near', 'coordinates'}:
        matches = [group for group, _ in nearest_groups(groups, value, spatial, settings)]
    else:
        matches = find_by_name(groups, value)
    if not matches:
        return 'No matching trail in local data.'
    if len(matches) != 1:
        return ambiguous_trails(matches)
    group = matches[0]
    if any(record['dataset'] != 'trails' for record in group):
        return compact_fields(f'mapped {role} not recorded; supplementary segments.', [group[0]['name']])
    endpoints = [record for record in snapshot.load_dataset('trail_endpoints')
                 if normalize_name(record['name']) == normalize_name(group[0]['name'])
                 and str(record['properties'].get('END_POINT') or '').strip().casefold() == role]
    # A name join must not override a conflicting recorded trail association.
    associations = [record['properties'].get('OBJECTID') for record in group]
    endpoint_associations = [record['properties'].get('OBJECTID') for record in endpoints]
    if endpoints:
        recorded = associations + endpoint_associations
        if any(ident is not None and (type(ident) is not int or ident < 0) for ident in recorded):
            return 'Endpoint trail association invalid; reference ambiguous.'
        if any(ident is not None for ident in recorded) and None in recorded:
            return 'Endpoint trail association incomplete; reference ambiguous.'
        if any(ident not in associations for ident in endpoint_associations):
            return 'Endpoint trail association conflicts; reference ambiguous.'
    if selected is not None:
        endpoints = [record for record in endpoints if str(record['properties'].get('OBJECTID_1')) == selected]
        if any(type(record['properties'].get('OBJECTID_1')) is not int for record in endpoints):
            return 'Endpoint source ID invalid; reference ambiguous.'
    if not endpoints:
        return compact_fields(f'mapped {role} not recorded' + (' for that ID.' if selected else '.'), [group[0]['name']])
    if len(endpoints) > 1:
        ids = [record['properties'].get('OBJECTID_1') for record in endpoints]
        if any(type(ident) is not int or ident < 0 for ident in ids) or len(set(ids)) != len(ids):
            return 'Multiple endpoints; source IDs missing or ambiguous.'
        # A proximity request has no supplied trail name. Keep its resolved name
        # and choices together so a subsequent named selection is possible.
        name = ' '.join(group[0]['name'].replace('|', '/').split())
        core = f'Multiple mapped {role}s: {name}; IDs ' + ','.join(str(ident) for ident in sorted(ids))
        if len(core.encode()) > reply_budget():
            return 'Endpoint choices exceed reply limit.'
        return compact_fields(core, [f'Use !trail NAME {role} id ID'])
    record = endpoints[0]
    geometry = record['geometry']
    values = geometry.get('coordinates') if isinstance(geometry, dict) and geometry.get('type') == 'Point' else None
    if not isinstance(values, (tuple, list)) or len(values) < 2:
        return f'Mapped {role} coordinates unavailable.'
    lon, lat = values[:2]
    if type(lat) not in (int, float) or type(lon) not in (int, float) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
        return f'Mapped {role} coordinates invalid.'
    core = f'mapped {role} {lat:.5f},{lon:.5f}; access unknown'
    ident = record['properties'].get('OBJECTID_1')
    if type(ident) is int and ident >= 0:
        core += f'; id {ident}'
    return compact_fields(core, [group[0]['name']])


def combined_reply(location, filters, groups, spatial, settings, eligible, field_values, attribute_fields):
    """Require every requested policy on every grouped segment before ranking."""
    def qualifies(group):
        for key in filters:
            if key != 'shade':
                if not eligible(group, 'trail', key):
                    return False
                continue
            for record in group:
                values = [str(record['properties'][field]).strip().casefold()
                          for field in attribute_fields['trail']['shade']
                          if record['properties'].get(field) is not None and str(record['properties'][field]).strip()]
                if not values or any(value not in SHADE_VALUES for value in values):
                    return False
        return True
    matches = nearest_groups([group for group in groups if qualifies(group)], location, spatial, settings)
    if not matches:
        return 'No matching trail for all filters in local data.'
    if len(matches) > 1:
        return ambiguous_trails([group for group, _ in matches])
    group, distance = matches[0]
    first = group[0]
    source = 'trail' if first['dataset'] == 'trails' else 'segment'
    # Source names cannot introduce optional-field separators into essential
    # qualifications. Segment records remain labeled even when grouped by name.
    identity = short_label(first['name'].replace('|', '/'), 25)
    conditions = '; '.join(key + ' ' + field_values(group, *attribute_fields['trail'][key]) for key in filters)
    core = f'{identity} ({source} ref); {conditions}'
    if spatial.repaired:
        core += '; geometry repaired'
    if len(core.encode()) > reply_budget():
        return compact_fields(f'{identity}: conditions exceed reply limit.')
    name = first['name'] if identity != first['name'] else ''
    return compact_fields(core, [name, f'{distance:.2f} mi map distance', 'Access status unknown'])
