"""Verified station inventory and compatible last-known observation access."""

import csv

from . import water_local, water_settings


def load_inventory(config):
    """Load exact agency-qualified identities from one verified inventory generation.

    Duplicate or malformed identifiers make the inventory ambiguous and are
    rejected. Source properties and geometry are retained without inference.
    """
    root = water_settings.collection(config)
    directory, _, pointer = water_local.generation(root, 'inventory', ['stations.geojson.gz'])
    document = water_local.read_json(directory / 'stations.geojson.gz')
    if document.get('type') != 'FeatureCollection' or not isinstance(document.get('features'), list):
        raise ValueError('Invalid station inventory')
    stations = {}
    for feature in document['features']:
        if not isinstance(feature, dict) or feature.get('type') != 'Feature':
            raise ValueError('Invalid station feature')
        properties = feature.get('properties')
        identifier = feature.get('id')
        if not isinstance(properties, dict) or not isinstance(identifier, str):
            raise ValueError('Invalid station identity')
        agency, number = properties.get('agency_code'), properties.get('monitoring_location_number')
        if (not isinstance(agency, str) or not isinstance(number, str) or not agency or not number
                or identifier != agency + '-' + number or identifier in stations):
            raise ValueError('Ambiguous station identity')
        stations[identifier] = feature
    # A concurrently replaced pointer cannot silently mix generations.
    if water_local.read_json(root / 'inventory.json') != pointer:
        raise ValueError('Station inventory changed; retry')
    return root, pointer, stations


def load_observations(root, inventory_pointer, now, max_age):
    """Read observations with query-time freshness and require matching inventory."""
    observation_pointer = water_local.read_json(root / 'observations.json')
    values, observed_inventory = water_local.readings(root, now, max_age, preserve_invalid=True)
    if water_local.read_json(root / 'observations.json') != observation_pointer:
        raise ValueError('Observations changed; retry')
    if observed_inventory != inventory_pointer:
        raise ValueError('Observations use a different station inventory')
    if water_local.read_json(root / 'inventory.json') != inventory_pointer:
        raise ValueError('Station inventory changed; retry')
    return values


def station_link(root, inventory_pointer, station_id):
    """Read the original exact NOAA identifier so reviews cannot override conflicts."""
    directory, _, pointer = water_local.generation(
        root, 'inventory', ['relationships/station_identifiers.csv'])
    if pointer != inventory_pointer:
        raise ValueError('Station link inventory changed; retry')
    with (directory / 'relationships/station_identifiers.csv').open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        if not {'station_id', 'nwps_lid'}.issubset(reader.fieldnames or []):
            raise ValueError('Invalid station link schema')
        matches = [row for row in reader if row['station_id'] == station_id]
    if len(matches) > 1:
        raise ValueError('Ambiguous station link')
    return matches[0]['nwps_lid'] or '' if matches else ''
