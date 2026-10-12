"""Manual and MeshCore GIS lookups using verified local GeoJSON snapshots."""

import argparse
import sys

try:
    from .gis_data import (BOUNDARY_LAYERS, PARK_LAYERS, GISUnavailable, Snapshot,
                           find_by_name, group_features, load_settings, normalize_name,
                           parse_command_query, SUBCOMMANDS, BOUNDARY_FILTERS, SETTINGS_FILE)
except ImportError:
    from gis_data import (BOUNDARY_LAYERS, PARK_LAYERS, GISUnavailable, Snapshot,
                          find_by_name, group_features, load_settings, normalize_name,
                          parse_command_query, SUBCOMMANDS, BOUNDARY_FILTERS, SETTINGS_FILE)


# Source fields and affirmative values are explicit so policy changes are reviewable.
ATTRIBUTE_FIELDS = {
    'trail': {
        'dogs': ('DOGS', 'DOG'), 'horses': ('HORSES', 'HORSE'),
        'bikes': ('BIKES', 'BICYCLE'), 'difficulty': ('DIFFICULTY',),
        'surface': ('SURFACE', 'SURFACE_TY'), 'shade': ('SUN_SHADE', 'SUNEXPO'),
    },
    'rec': {
        'type': ('TYPE',), 'parking': ('PARKING',), 'restrooms': ('RESTROOM',),
        'water': ('DRINKING_WATER',), 'picnic': ('PICNIC_AREA',),
        'fishing': ('FISHING',), 'boatlaunch': ('BOAT_LAUNCH',),
        'boatrental': ('BOAT_RENTAL',), 'playground': ('PLAYGROUND',),
        'horsetrailers': ('HORSE_PARKING',),
    },
    'park': {'status': ('STATUS',), 'agency': ('AGENCY_NAM', 'AGNCY_NAME')},
}
FILTER_VALUES = {
    'trail': {
        'dogs': {'yes', 'limited to park hours'},
        'horses': {'yes'}, 'bikes': {'yes', 'yes l'},
    },
    'rec': {
        'parking': {'yes', 'lot', 'limited'}, 'restrooms': {'yes', 'ada'},
        'water': {'yes'}, 'picnic': {'yes'}, 'fishing': {'yes'},
        'boatlaunch': {'yes'}, 'boatrental': {'yes'}, 'playground': {'yes'},
        'horsetrailers': {'phyes', 'yes'},
    },
}


def field_values(group, *fields):
    """Preserve distinct source values and qualifications across grouped records."""
    values = []
    for record in group:
        for field in fields:
            value = record['properties'].get(field)
            if value is not None and str(value).strip() and str(value) not in values:
                values.append(str(value))
    return '/'.join(values) if values else 'not recorded'


def number(value, units):
    """Format source numbers without exposing floating-point storage artifacts."""
    try:
        return f'{float(value):.2f}'.rstrip('0').rstrip('.') + ' ' + units
    except (TypeError, ValueError):
        return 'not recorded'


def summary(group):
    """Label a result with source category and park status when available."""
    record = group[0]
    label = f'{record["category"]}: {record["name"]}'
    status = field_values(group, 'STATUS')
    return label + (f' [{status}]' if record['category'] == 'Park' and status != 'not recorded' else '')


def short_list(labels, limit):
    """Bound result lists while explicitly reporting omitted matches."""
    if not labels:
        return 'none in local data'
    text = '; '.join(labels[:limit])
    if len(labels) > limit:
        text += f'; +{len(labels) - limit} more'
    return text


def trail_groups(snapshot):
    """Prefer primary trail records; retain supplementary trails absent from that layer."""
    primary = snapshot.load_dataset('trails')
    names = {normalize_name(record['name']) for record in primary}
    extra = [record for record in snapshot.load_dataset('additional_trails')
             if record['named'] and normalize_name(record['name']) not in names]
    return group_features(primary + extra)


def area_groups(snapshot, layers):
    """Group named park polygons, preserving all original status and agency fields."""
    return group_features([record for layer in layers for record in snapshot.load_dataset(layer)])


def format_trail_reply(group, snapshot, spatial, settings):
    """Describe primary trail attributes and mapped area overlap without routing claims."""
    properties = group[0]['properties']
    primary = group[0]['dataset'] == 'trails'
    distance = number(properties.get('LENGTH_MIL'), 'mi') if primary else 'segment data; total not inferred'
    difficulty = field_values(group, 'DIFFICULTY').replace('Difficult', 'Strenuous')
    text = (f'{summary(group)}; {distance}; {difficulty}; '
            f'gain {number(properties.get("ELEVATION_GAIN"), "ft")}; '
            f'surface {field_values(group, "SURFACE", "SURFACE_TY")}; '
            f'sun {field_values(group, "SUN_SHADE", "SUNEXPO")}; '
            f'dogs {field_values(group, "DOGS", "DOG")}; '
            f'horses {field_values(group, "HORSES", "HORSE")}; '
            f'bikes {field_values(group, "BIKES", "BICYCLE")}.')
    if primary:
        text += f' Estimated time {number(properties.get("HOUR"), "hr")} (3 mph; terrain excluded).'
    endpoints = [record for record in snapshot.load_dataset('trail_endpoints')
                 if normalize_name(record['name']) == normalize_name(group[0]['name'])]
    starts = [record for record in endpoints if record['properties'].get('END_POINT') == 'START'
              and record['geometry'] is not None]
    if starts:
        lon, lat = starts[0]['geometry']['coordinates'][:2]
        text += f' Mapped start {lat:.5f},{lon:.5f}.'
    areas = spatial.intersections(group, area_groups(snapshot, BOUNDARY_LAYERS))
    text += ' Overlaps: ' + short_list([summary(area) for area in areas], settings['max_results']) + '.'
    description = properties.get('TRAIL_DESC')
    if description and settings['description_characters']:
        limit = settings['description_characters']
        text += ' ' + description[:limit].strip() + ('...' if len(description) > limit else '')
    return text


def format_recreation_reply(group):
    """Describe recorded amenities, retaining limited parking and accessible restroom values."""
    labels = [('TYPE', 'type'), ('PARKING', 'parking'), ('RESTROOM', 'restroom'),
              ('DRINKING_WATER', 'water'), ('PICNIC_AREA', 'picnic'), ('FISHING', 'fishing'),
              ('BOAT_LAUNCH', 'boat launch'), ('BOAT_RENTAL', 'boat rental'),
              ('PLAYGROUND', 'playground')]
    text = summary(group) + '; ' + '; '.join(f'{label} {field_values(group, field)}' for field, label in labels)
    trailer = field_values(group, 'HORSE_PARKING')
    if trailer == 'phYes':
        text += '; horse trailer parking Yes'
    return text + '.'


def format_peak_reply(group):
    """Report stored peak elevation in feet and point coordinates when available."""
    record = group[0]
    text = summary(group) + '; elevation ' + number(record['properties'].get('ELEVATION'), 'ft')
    if record['geometry'] is not None:
        lon, lat = record['geometry']['coordinates'][:2]
        text += f'; {lat:.5f},{lon:.5f}'
    return text + '.'


def format_park_reply(group, snapshot, spatial, settings):
    """Describe grouped park records and geometric associations, not accessible routes."""
    trails = spatial.intersections(group, trail_groups(snapshot))
    recreation = spatial.intersections(group, group_features(snapshot.load_dataset('recreation_points')))
    return (f'{summary(group)}; {len(group)} source polygon records; '
            f'agency {field_values(group, "AGENCY_NAM", "AGNCY_NAME")}. '
            'Intersecting trails: ' + short_list([item[0]['name'] for item in trails], settings['max_results']) +
            '. Recreation: ' + short_list([item[0]['name'] for item in recreation], settings['max_results']) + '.')


def bounded_reply(body, spatial, settings):
    """Bound the UTF-8 reply size and retain any geometry-repair note."""
    suffix = ' Geometry repaired for calculation.' if spatial is not None and spatial.repaired else ''
    budget = settings['max_reply_bytes'] - len(suffix.encode('utf-8'))
    body = ' '.join(body.split())
    if len(body.encode('utf-8')) > budget:
        body = body.encode('utf-8')[:budget - 3].decode('utf-8', 'ignore').rstrip() + '...'
    return body + suffix


def eligible(group, kind, attribute):
    """Require affirmative policy/amenity values before spatial ranking.

    Every grouped record must explicitly qualify. Missing, negative, unknown,
    or conflicting values exclude the group. Source qualifications remain in
    the displayed attribute instead of being reduced to an unconditional Yes.
    """
    allowed = FILTER_VALUES.get(kind, {}).get(attribute)
    if allowed is None:
        return True
    fields = ATTRIBUTE_FIELDS[kind][attribute]
    for record in group:
        values = [str(record['properties'][field]).strip().casefold() for field in fields
                  if record['properties'].get(field) is not None
                  and str(record['properties'][field]).strip()]
        if not values or any(value not in allowed for value in values):
            return False
    return True


def command_help(kind):
    """Describe accepted syntax and subcommands without loading GIS datasets."""
    choices = ', '.join(SUBCOMMANDS[kind])
    if kind == 'boundary':
        return f'!boundary [CATEGORY] LAT LON | near LAT LON [MILES] | trail NAME. Categories: {choices}.'
    return (f'!{kind} NAME [ATTRIBUTE] | [ATTRIBUTE] near LAT LON [MILES]. '
            f'Subcommands: {choices}. No miles: closest only.')


def attribute_text(kind, attribute, group, snapshot, spatial, settings):
    """Format only the requested field or association, retaining unknown values."""
    fields = ATTRIBUTE_FIELDS.get(kind, {}).get(attribute)
    if fields:
        value = field_values(group, *fields)
        if attribute == 'difficulty':
            value = value.replace('Difficult', 'Strenuous')
        if attribute == 'horsetrailers':
            value = value.replace('phYes', 'Yes')
        return f'{attribute} {value}'
    properties = group[0]['properties']
    if attribute == 'location':
        locations = []
        for record in group:
            if record['geometry'] is not None:
                lon, lat = record['geometry']['coordinates'][:2]
                locations.append(f'{lat:.5f},{lon:.5f}')
        return 'location ' + ('; '.join(dict.fromkeys(locations)) or 'not recorded')
    if attribute == 'elevation':
        return 'elevation ' + number(properties.get('ELEVATION'), 'ft')
    if kind == 'trail':
        primary = group[0]['dataset'] == 'trails'
        if attribute == 'length':
            return 'length ' + (number(properties.get('LENGTH_MIL'), 'mi') if primary
                                else 'segment data; total not inferred')
        if attribute == 'gain':
            return 'gain ' + number(properties.get('ELEVATION_GAIN'), 'ft')
        if attribute == 'time':
            return ('estimated time ' + number(properties.get('HOUR'), 'hr') + ' (3 mph; terrain excluded)'
                    if primary else 'estimated time not recorded')
        if attribute == 'description':
            description = properties.get('TRAIL_DESC')
            limit = settings['description_characters']
            if not description:
                return 'description not recorded'
            if not limit:
                return 'description omitted by settings'
            return 'description ' + description[:limit].strip() + ('...' if len(description) > limit else '')
        if attribute == 'start':
            starts = [record for record in snapshot.load_dataset('trail_endpoints')
                      if normalize_name(record['name']) == normalize_name(group[0]['name'])
                      and record['properties'].get('END_POINT') == 'START'
                      and record['geometry'] is not None]
            if not starts:
                return 'mapped start not recorded'
            lon, lat = starts[0]['geometry']['coordinates'][:2]
            return f'mapped start {lat:.5f},{lon:.5f}'
        if attribute == 'areas':
            found = spatial.intersections(group, area_groups(snapshot, BOUNDARY_LAYERS))
            return 'overlaps ' + short_list([summary(area) for area in found], settings['max_results'])
    if kind == 'park' and attribute in {'trails', 'recreation'}:
        targets = (trail_groups(snapshot) if attribute == 'trails' else
                   group_features(snapshot.load_dataset('recreation_points')))
        found = spatial.intersections(group, targets)
        return attribute + ' ' + short_list([item[0]['name'] for item in found], settings['max_results'])
    raise ValueError(f'Unsupported !{kind} attribute: {attribute}.')


def feature_reply(kind, group, attribute, snapshot, spatial, settings):
    """Return compact identification, one attribute, or an explicitly requested full reply."""
    name = group[0]['name']
    if attribute is None:
        return f'{group[0]["category"]}: {name}. Subcommands: {", ".join(SUBCOMMANDS[kind])}.'
    if attribute != 'info':
        detail = attribute_text(kind, attribute, group, snapshot, spatial, settings)
        return f'{name}: {detail}' + ('' if detail.endswith('.') else '.')
    if kind == 'trail':
        return format_trail_reply(group, snapshot, spatial, settings)
    if kind == 'rec':
        return format_recreation_reply(group)
    if kind == 'peak':
        return format_peak_reply(group)
    return format_park_reply(group, snapshot, spatial, settings)


def lookup(kind, query, settings=None):
    """Execute one offline name, proximity, containment, or trail-area query."""
    try:
        from .gis_spatial import Spatial
    except ImportError:
        from gis_spatial import Spatial
    settings = load_settings() if settings is None else settings
    mode, value, attribute = parse_command_query(kind, query)
    if mode == 'help':
        return bounded_reply(command_help(kind), None, settings)
    snapshot = Snapshot(settings['data_directory'])
    spatial = Spatial(settings)
    boundary_layers = BOUNDARY_FILTERS.get(attribute, BOUNDARY_LAYERS)
    if kind == 'trail' or kind == 'boundary' and mode == 'trail':
        groups = trail_groups(snapshot)
    elif kind == 'rec':
        groups = group_features(snapshot.load_dataset('recreation_points'))
    elif kind == 'peak':
        groups = group_features([record for record in snapshot.load_dataset('peaks')
                                 if record['named'] or settings['include_unnamed_peaks']])
    else:
        groups = area_groups(snapshot, boundary_layers if kind == 'boundary' else PARK_LAYERS)
    if mode in {'coordinates', 'near'}:
        point = spatial.point(*value[:2])
        radius = value[2] if len(value) == 3 else None
        if radius is not None and radius > settings['maximum_radius_miles']:
            raise ValueError(f'Radius must not exceed {settings["maximum_radius_miles"]:g} miles.')
        if kind == 'boundary' and mode == 'coordinates':
            found = spatial.containing(groups, point)
            body = 'Mapped areas: ' + short_list(
                [f'{relation} {summary(group)}' for group, relation in found], settings['max_results']) + '.'
        else:
            groups = [group for group in groups if eligible(group, kind, attribute)]
            found = spatial.nearby(groups, point, radius)
            labels = []
            for group, distance in found:
                label = f'{group[0]["category"]}: {group[0]["name"]} ({distance:.2f} mi)'
                if attribute and kind != 'boundary':
                    if attribute == 'info':
                        label = f'{distance:.2f} mi; ' + feature_reply(kind, group, attribute, snapshot, spatial, settings)
                    else:
                        label += '; ' + attribute_text(kind, attribute, group, snapshot, spatial, settings)
                labels.append(label)
            if not found:
                qualifier = f' for {attribute}' if attribute else ''
                extent = f' within {radius:g} mi' if radius is not None else ''
                body = f'No matching {kind}{qualifier}{extent} in local data.'
            else:
                prefix = 'Closest, map distance: ' if radius is None else f'Within {radius:g} mi, map distance: '
                body = prefix + short_list(labels, settings['max_results'])
                if not body.endswith('.'):
                    body += '.'
    else:
        matches = find_by_name(groups, value)
        if not matches:
            body = f'No matching {kind} in local data: {value}.'
        elif len(matches) > 1:
            body = 'Multiple matches; enter a full name: ' + short_list(
                [summary(group) for group in matches], settings['max_results']) + '.'
        elif kind == 'boundary':
            areas = spatial.intersections(matches[0], area_groups(snapshot, boundary_layers))
            body = 'Trail overlaps: ' + short_list([summary(group) for group in areas], settings['max_results']) + '.'
        else:
            body = feature_reply(kind, matches[0], attribute, snapshot, spatial, settings)
    snapshot.verify_unchanged()
    return bounded_reply(body, spatial, settings)


def main(argv=None, *, kind=None):
    """Run a fixed command with positional input or the generic --kind/--query CLI.

    Command programs supply kind so received arguments cannot select another
    command. Shared lookup, settings, output limits, and error handling are retained.
    """
    parser = argparse.ArgumentParser(description=f'Local {kind} GIS lookup.' if kind else __doc__)
    if kind is None:
        parser.add_argument('--kind', required=True, choices=['trail', 'rec', 'peak', 'park', 'boundary'])
        parser.add_argument('--query', required=True)
    else:
        parser.add_argument('query', nargs='*', help='NAME [ATTRIBUTE] or [ATTRIBUTE] near LAT LON [MILES]; help lists options.')
    parser.add_argument('--settings', default=str(SETTINGS_FILE))
    args = parser.parse_args(argv)
    query = (' '.join(args.query) or 'help') if kind is not None else args.query
    try:
        print(lookup(kind if kind is not None else args.kind, query, load_settings(args.settings)))
    except ValueError as error:
        print(f'GIS lookup could not complete: {error}')
        return 0
    except (OSError, KeyError, TypeError, RuntimeError, ImportError) as error:
        print('Local GIS data unavailable; check the datasets, dependencies, or refresh state.')
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
