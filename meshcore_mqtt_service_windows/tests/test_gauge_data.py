"""Station identity and inventory-generation consistency checks."""
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import gauge_data


def station(agency, number):
    """Build one source-shaped station with an unmodified identifier."""
    return {'id': agency + '-' + number, 'type': 'Feature', 'geometry': None,
            'properties': {'agency_code': agency, 'monitoring_location_number': number}}


class GaugeDataTests(unittest.TestCase):
    def setUp(self):
        self.pointer = {'generation': 'one'}
        self.features = [station('USGS', '00123'), station('CA001', '00123')]
        self.collection = patch.object(gauge_data.water_settings, 'collection', return_value=Path('fixture'))
        self.generation = patch.object(gauge_data.water_local, 'generation', return_value=(Path('fixture/gen'), {}, self.pointer))
        self.read = patch.object(gauge_data.water_local, 'read_json', side_effect=self.read_json)
        for patcher in (self.collection, self.generation, self.read):
            patcher.start()
            self.addCleanup(patcher.stop)

    def read_json(self, path):
        return self.pointer if path.name == 'inventory.json' else {'type': 'FeatureCollection', 'features': self.features}

    def test_exact_namespaces_and_leading_zeroes(self):
        _, _, records = gauge_data.load_inventory({})
        self.assertEqual(set(records), {'USGS-00123', 'CA001-00123'})
        self.assertNotIn('USGS-123', records)

    def test_duplicate_or_conflicting_identifiers_fail(self):
        self.features.append(station('USGS', '00123'))
        with self.assertRaisesRegex(ValueError, 'Ambiguous'):
            gauge_data.load_inventory({})
        self.features.pop()
        self.features[0]['properties']['agency_code'] = 'OTHER'
        with self.assertRaisesRegex(ValueError, 'Ambiguous'):
            gauge_data.load_inventory({})

    def test_observation_generation_must_match(self):
        with patch.object(gauge_data.water_local, 'readings', return_value=({'USGS-00123': []}, {'generation': 'other'})):
            with self.assertRaisesRegex(ValueError, 'different station inventory'):
                gauge_data.load_observations(Path('fixture'), self.pointer, 100, 60)
        with patch.object(gauge_data.water_local, 'readings', return_value=({'USGS-00123': []}, self.pointer)) as reader:
            self.assertEqual(gauge_data.load_observations(Path('fixture'), self.pointer, 100, 60), {'USGS-00123': []})
            reader.assert_called_once_with(Path('fixture'), 100, 60, preserve_invalid=True)

    def test_station_link_generation_and_duplicate_identity(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'relationships').mkdir()
            path = root / 'relationships/station_identifiers.csv'
            path.write_text('station_id,nwps_lid\nUSGS-00123,ABCDE\nCA001-00123,OTHER\n')
            with patch.object(gauge_data.water_local, 'generation', return_value=(root, {}, self.pointer)):
                self.assertEqual(gauge_data.station_link(root, self.pointer, 'USGS-00123'), 'ABCDE')
                with self.assertRaisesRegex(ValueError, 'changed'):
                    gauge_data.station_link(root, {'generation': 'other'}, 'USGS-00123')
                path.write_text(path.read_text() + 'USGS-00123,OTHER\n')
                with self.assertRaisesRegex(ValueError, 'Ambiguous'):
                    gauge_data.station_link(root, self.pointer, 'USGS-00123')


if __name__ == '__main__':
    unittest.main()
