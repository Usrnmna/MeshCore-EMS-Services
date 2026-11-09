"""Offline pointing, terrain, identity, freshness and command integration checks."""
import asyncio
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import math
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
import rasterio
from rasterio.transform import from_origin
import responder
from scripts import satellite_lookup as catalog
from scripts import satellite_pointing as pointing
from scripts import satellite_terrain as terrain
from test_satellite_lookup import SCHEMA


class PointingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.dbpath = self.root / 'catalog.sqlite3'
        self.db = sqlite3.connect(self.dbpath)
        self.addCleanup(self.db.close)
        self.db.executescript(SCHEMA)
        self.db.execute('PRAGMA user_version=1')
        self.db.execute("INSERT INTO metadata VALUES('status_max_age_days','30')")
        self.db.execute('INSERT INTO satellites VALUES(?,?,?,?,?)',
                        ('sat1', 12345, 'Fixture', 'in orbit', json.dumps({'satellite_id': 'sat1', 'norad_id': 12345})))
        self.now = datetime.now(timezone.utc).replace(microsecond=0)
        self.epoch = self.now - timedelta(days=1)
        self.elements = dict(OBJECT_NAME='Fixture', OBJECT_ID='2024-001A', EPOCH=self.epoch.isoformat(),
                             MEAN_MOTION=15.5, ECCENTRICITY=.0003, INCLINATION=51.6,
                             RA_OF_ASC_NODE=120., ARG_OF_PERICENTER=140., MEAN_ANOMALY=205.,
                             EPHEMERIS_TYPE=0, CLASSIFICATION_TYPE='U', NORAD_CAT_ID=12345,
                             ELEMENT_SET_NO=1, REV_AT_EPOCH=1, BSTAR=.0001,
                             MEAN_MOTION_DOT=0., MEAN_MOTION_DDOT=0.)
        self.orbit()
        self.tif = self.root / 'terrain.tif'
        self.raster(np.full((4, 4), 50., dtype='float64'))
        self.values = dict(database=str(self.dbpath), orbit_max_age_days=14,
                           pointing={'terrain_sources': [self.entry()]})
        self.save()
        mocked = patch.object(catalog, 'ROOT', self.root)
        mocked.start()
        self.addCleanup(mocked.stop)
        environment = patch.dict(os.environ, {'MESHCORE_SATELLITE_SETTINGS': str(self.root / 'satellite-settings.json')})
        environment.start()
        self.addCleanup(environment.stop)

    def orbit(self, source='fixture:orbit', elements=None, epoch=None, format='OMM_JSON'):
        """Install a deterministic local orbit with exact identity metadata."""
        stamp = (epoch or self.epoch).isoformat()
        self.db.execute('INSERT OR REPLACE INTO orbits VALUES(?,?,?,?,?,?)',
                        ('sat1', source, format, stamp, self.now.isoformat(), json.dumps(elements or self.elements)))
        self.db.commit()

    def raster(self, values, crs='EPSG:4326', transform=None, **extra):
        """Create a small synthetic height surface; never use production terrain."""
        with rasterio.open(self.tif, 'w', driver='GTiff', width=4, height=4, count=1,
                           dtype='float64', crs=crs, transform=transform or from_origin(-123, 39, 1, 1),
                           nodata=-9999, **extra) as target:
            target.write(values, 1)

    def entry(self, **changes):
        result = dict(id='dem', path=str(self.tif), bytes=self.tif.stat().st_size,
                      sha256=hashlib.sha256(self.tif.read_bytes()).hexdigest(),
                      units='m', vertical_crs='EPSG:4979', source='synthetic fixture')
        result.update(changes)
        return result

    def save(self):
        (self.root / 'satellite-settings.json').write_text(json.dumps(self.values), encoding='utf-8')
        (self.root / 'config.json').write_text('{}', encoding='utf-8')

    def query(self, text='12345 37.5 -121.5'):
        return pointing.lookup(text, now=self.now)

    def test_parse_coordinates_agl_and_limits(self):
        self.assertEqual(pointing.parse('12345 -90 180 agl 2')['agl'], 2)
        for text in ('012345 0 0', '12345 nan 0', '12345 91 0', '12345 0 -181',
                     '12345 0 0 agl -1', '12345 0 0 agl inf', '12345 0 0 agl 1001',
                     '12345 0 0 agl 1 agl 2', '12345 0 0 height 10', '12345 0', 'x'*151, '12345 0 0\n'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                pointing.parse(text)

    def test_height_and_agl_used_by_real_propagation(self):
        ground = self.query()
        antenna = self.query('12345 37.5 -121.5 agl 100')
        self.assertEqual(ground['observer_height_wgs84_m'], 50)
        self.assertEqual(antenna['observer_height_wgs84_m'], 150)
        self.assertNotEqual(ground['range_km'], antenna['range_km'])
        self.assertEqual(ground['terrain']['sampling'], 'containing pixel; no interpolation')
        self.assertEqual(ground['refraction'], 'none')

    def test_terrain_variation_changes_position_and_negative_heights(self):
        first = self.query()
        self.raster(np.full((4, 4), -400.))
        self.values['pointing']['terrain_sources'] = [self.entry()]
        self.save()
        second = self.query()
        self.assertEqual(second['observer_height_wgs84_m'], -400)
        self.assertNotEqual(first['range_km'], second['range_km'])

    def test_units_scale_offset_and_conflicts(self):
        with rasterio.open(self.tif, 'r+') as raster:
            raster.scales = (2.,)
            raster.offsets = (10.,)
        self.values['pointing']['terrain_sources'] = [self.entry(units='ft')]
        self.save()
        self.assertAlmostEqual(self.query()['observer_height_wgs84_m'], 110*.3048)
        with rasterio.open(self.tif, 'r+') as raster:
            raster.set_band_unit(1, 'm')
        self.values['pointing']['terrain_sources'] = [self.entry(units='ft')]
        self.save()
        with self.assertRaisesRegex(ValueError, 'units'):
            self.query()

    def test_nodata_and_half_open_boundaries(self):
        with self.assertRaisesRegex(ValueError, 'coverage'):
            self.query('12345 35 -119')
        self.assertEqual(self.query('12345 39 -123')['observer_height_wgs84_m'], 50)
        values = np.full((4, 4), 50.)
        values[1, 1] = -9999
        self.raster(values)
        self.values['pointing']['terrain_sources'] = [self.entry()]
        self.save()
        with self.assertRaisesRegex(ValueError, 'NoData'):
            self.query()

    def test_overlapping_sources_require_selection(self):
        self.values['pointing']['terrain_sources'].append(self.entry(id='other'))
        self.save()
        with self.assertRaisesRegex(ValueError, 'Select terrain'):
            self.query()
        self.assertEqual(self.query('12345 37.5 -121.5 terrain other')['terrain']['source_id'], 'other')
        with self.assertRaisesRegex(ValueError, 'Unknown terrain'):
            self.query('12345 37.5 -121.5 terrain missing')

    def test_no_terrain_does_not_use_peak_or_zero(self):
        self.values['pointing']['terrain_sources'] = []
        self.save()
        with self.assertRaisesRegex(ValueError, 'GIS terrain unavailable'):
            self.query()

    def test_integrity_and_generation_changes(self):
        self.values['pointing']['terrain_sources'][0]['sha256'] = '0'*64
        self.save()
        with self.assertRaisesRegex(ValueError, 'integrity'):
            self.query()
        self.values['pointing']['terrain_sources'] = [self.entry()]
        with self.assertRaisesRegex(ValueError, 'changed'):
            with terrain.terrain(self.values, self.root, 37.5, -121.5):
                with self.tif.open('ab') as stream:
                    stream.write(b'changed')

    def test_unknown_vertical_datum_and_missing_local_grids(self):
        self.values['pointing']['terrain_sources'] = [self.entry(vertical_crs='EPSG:5703')]
        self.save()
        # Simulate an environment with no eligible local vertical operation.
        actual = terrain.transformer
        def without_grid(source, target, lat, lon):
            if getattr(source, 'is_compound', False):
                raise ValueError('Required local datum transformation unavailable')
            return actual(source, target, lat, lon)
        with patch.object(terrain, 'transformer', side_effect=without_grid):
            with self.assertRaisesRegex(ValueError, 'datum transformation'):
                self.query()
        self.values['pointing']['terrain_sources'][0]['vertical_crs'] = 'EPSG:4326'
        self.save()
        with self.assertRaisesRegex(ValueError, 'vertical CRS'):
            self.query()

    def test_vertical_conversion_result_is_applied(self):
        self.values['pointing']['terrain_sources'] = [self.entry(vertical_crs='EPSG:5703')]
        self.save()
        actual = terrain.transformer
        conversion = SimpleNamespace(operations=[], description='fixture vertical conversion',
                                     transform=lambda x, y, h, **kw: (x, y, h+20))
        with patch.object(terrain, 'transformer', side_effect=lambda source, target, lat, lon:
                          conversion if getattr(source, 'is_compound', False) else actual(source, target, lat, lon)):
            self.assertEqual(self.query()['observer_height_wgs84_m'], 70)

    def test_projected_wgs84_terrain(self):
        from pyproj import Transformer
        x, y = Transformer.from_crs(4326, 32610, always_xy=True).transform(-121.5, 37.5)
        self.raster(np.full((4, 4), 80.), crs='EPSG:32610', transform=from_origin(x-150, y+150, 100, 100))
        self.values['pointing']['terrain_sources'] = [self.entry()]
        self.save()
        result = self.query()
        self.assertEqual(result['observer_height_wgs84_m'], 80)
        self.assertEqual(result['terrain']['resolution'], [100., 100.])

    def test_exact_unknown_conflicting_and_retired_identities(self):
        with self.assertRaisesRegex(ValueError, 'not in'):
            self.query('54321 37.5 -121.5')
        self.db.execute("INSERT INTO satellites VALUES('duplicate',12345,'Other','in orbit','{}')")
        self.db.commit()
        with self.assertRaisesRegex(ValueError, 'Ambiguous'):
            self.query()
        self.db.execute("DELETE FROM satellites WHERE satellite_id='duplicate'")
        self.db.execute("UPDATE satellites SET lifecycle='retired'")
        self.db.commit()
        with self.assertRaisesRegex(ValueError, 'lifecycle'):
            self.query()

    def test_orbit_mismatch_stale_future_and_epoch_mismatch(self):
        self.orbit(elements=dict(self.elements, NORAD_CAT_ID=54321))
        with self.assertRaisesRegex(ValueError, 'identity mismatch'):
            self.query()
        for days, phrase in ((31, 'Stale'), (-1, 'Future')):
            epoch = self.now - timedelta(days=days)
            self.orbit(elements=dict(self.elements, EPOCH=epoch.isoformat()), epoch=epoch)
            with self.assertRaisesRegex(ValueError, phrase):
                self.query()
        self.orbit(epoch=self.epoch-timedelta(days=1))
        with self.assertRaisesRegex(ValueError, 'epoch disagrees'):
            self.query()

    def test_multiple_orbits_explicit_selection_and_partial_sources(self):
        self.orbit(source='fixture:second')
        with self.assertRaisesRegex(ValueError, 'Select orbit'):
            self.query()
        selector = pointing.orbit_id({'source_url': 'fixture:second', 'format': 'OMM_JSON'})
        self.assertEqual(self.query('12345 37.5 -121.5 orbit '+selector)['orbit_source'], 'fixture:second')
        self.orbit(source='fixture:second', epoch=self.now-timedelta(days=50))
        self.assertTrue(self.query()['partial_orbit_coverage'])

    def test_unsupported_or_missing_orbits_and_policy(self):
        self.db.execute('DELETE FROM orbits')
        self.db.commit()
        with self.assertRaisesRegex(ValueError, 'No eligible'):
            self.query()
        self.orbit(format='UNSUPPORTED')
        with self.assertRaisesRegex(ValueError, 'Unsupported orbit'):
            self.query()
        self.values['orbit_max_age_days'] = float('nan')
        self.save()
        with self.assertRaisesRegex(ValueError, 'freshness policy'):
            self.query()

    def test_freshness_changes_at_query_time(self):
        self.query()
        with self.assertRaisesRegex(ValueError, 'Stale'):
            pointing.lookup('12345 37.5 -121.5', now=self.now+timedelta(days=15))

    def test_pointing_against_independent_teme_to_enu_calculation(self):
        # Independent observer geometry: SGP4 TEME, Vallado GMST, WGS84 ECEF,
        # then the standard local east/north/up rotation (no Skyfield altaz).
        from sgp4.api import Satrec, jday
        from sgp4 import omm
        from sgp4.propagation import gstime
        result = self.query()
        model = Satrec()
        elements = dict(self.elements, EPOCH=self.epoch.strftime('%Y-%m-%dT%H:%M:%S.%f'))
        omm.initialize(model, elements)
        date = self.now
        jd, fraction = jday(date.year, date.month, date.day, date.hour, date.minute, date.second)
        error, position, velocity = model.sgp4(jd, fraction)
        self.assertEqual(error, 0)
        theta = gstime(jd+fraction)
        x, y, z = position
        fixed = np.array([math.cos(theta)*x+math.sin(theta)*y, -math.sin(theta)*x+math.cos(theta)*y, z])*1000
        lat, lon = map(math.radians, [37.5, -121.5])
        eccentricity = 6.6943799901413165e-3
        radius = 6378137/math.sqrt(1-eccentricity*math.sin(lat)**2)
        observer = np.array([(radius+50)*math.cos(lat)*math.cos(lon), (radius+50)*math.cos(lat)*math.sin(lon),
                             (radius*(1-eccentricity)+50)*math.sin(lat)])
        delta = fixed-observer
        east = np.dot([-math.sin(lon), math.cos(lon), 0], delta)
        north = np.dot([-math.sin(lat)*math.cos(lon), -math.sin(lat)*math.sin(lon), math.cos(lat)], delta)
        up = np.dot([math.cos(lat)*math.cos(lon), math.cos(lat)*math.sin(lon), math.sin(lat)], delta)
        az = math.degrees(math.atan2(east, north)) % 360
        el = math.degrees(math.atan2(up, math.hypot(east, north)))
        self.assertAlmostEqual(result['azimuth_true_deg'], az, delta=.05)
        self.assertAlmostEqual(result['elevation_deg'], el, delta=.05)

    def test_published_vallado_sgp4_reference_and_tle_checksum(self):
        from skyfield.api import load
        line1 = '1 00005U 58002B   00179.78495062  .00000023  00000-0  28098-4 0  4753'
        line2 = '2 00005  34.2682 348.7242 1859667 331.7664  19.3264 10.82419157413667'
        row = dict(format='TLE', epoch='2000-06-27T18:50:19.733568Z',
                   data_json=json.dumps(dict(tle1=line1, tle2=line2, norad_cat_id=5)))
        model = pointing.build_orbit(row, dict(norad_id=5, satellite_id='reference'), load.timescale(builtin=True))
        error, position, _ = model.model.sgp4_tsince(0)
        self.assertEqual(error, 0)
        np.testing.assert_allclose(position, [7022.46529266, -1400.08296755, .03995155], atol=1e-7)
        row['data_json'] = json.dumps(dict(tle1=line1[:-1]+'0', tle2=line2))
        with self.assertRaisesRegex(ValueError, 'checksum'):
            pointing.build_orbit(row, dict(norad_id=5, satellite_id='reference'), load.timescale(builtin=True))

    def test_horizon_zenith_and_radio_qualifications(self):
        result = self.query()
        for elevation in (-5, 5):
            report = dict(result, elevation_deg=elevation, above_geometric_horizon=elevation>0)
            text = pointing.render(report)
            self.assertIn('above' if elevation>0 else 'below', text)
            self.assertIn('geom', text)
            self.assertIn('RF/sightline unverified', text)
            for sender in ('Reader', 'é'*40):
                with patch.dict(os.environ, {'MESHCORE_SENDER': sender}):
                    text = pointing.render(report)
                    self.assertLessEqual(len(('@'+sender+' '+text).encode()), 150)
        angles = SimpleNamespace(altaz=lambda: (SimpleNamespace(degrees=90), SimpleNamespace(degrees=123),
                                               SimpleNamespace(km=500)), message=None)
        class Model:
            def __sub__(self, observer):
                return SimpleNamespace(at=lambda time: angles)
        from skyfield.api import load
        result = pointing.angles(Model(), load.timescale(builtin=True), self.now, 37.5, -121.5, 50)
        self.assertIsNone(result['azimuth_true_deg'])

    def test_direct_and_service_invocation_discovery_and_local_json(self):
        root = Path(__file__).resolve().parents[1]
        config = json.loads((root/'config.json').read_bytes())['responder']
        spec = config['commands']['!satpoint']
        direct = subprocess.run([sys.executable, str(root/spec['script']), '--json', '12345', '37.5', '-121.5'],
                                capture_output=True, text=True, encoding='utf-8', timeout=20)
        self.assertEqual(direct.returncode, 0, direct.stderr)
        self.assertEqual(json.loads(direct.stdout)['observer_height_wgs84_m'], 50)
        request = dict(sender='Alice', channel_name='Test', channel_id='default', channel_index=3, id='w12',
                       phrase='!satpoint 12345 37.5 -121.5', command='!satpoint', arguments=['12345 37.5 -121.5'])
        output, diagnostic = asyncio.run(responder.run_script(root, spec, request, config))
        self.assertFalse(diagnostic)
        self.assertIn('hW84=50.0m', output)
        self.assertLessEqual(len(responder.reply_parts('Alice', output, max_parts=1)[0].encode()), 150)
        request.update(command='!help', arguments=['!satpoint'], phrase='!help !satpoint')
        output, diagnostic = asyncio.run(responder.run_script(root, config['commands']['!help'], request, config))
        self.assertFalse(diagnostic)
        self.assertIn('Partial', output)
        output = io.StringIO()
        with redirect_stdout(output), patch.dict(os.environ, {'MESHCORE_REQUEST_ID': 'service'}):
            pointing.main(['--json', '12345 37.5 -121.5'])
        self.assertIn('local-only', output.getvalue())

    def test_explicit_removal_and_catalog_schema(self):
        shared = self.root / 'data'
        shared.mkdir()
        self.values['database'] = str(shared/'satellites/satellites.sqlite3')
        self.save()
        (shared/'datasets.json').write_text(json.dumps({'schema': 1, 'datasets': {'satellites': {'active': None}}}), encoding='utf-8')
        with patch.dict(os.environ, {'MESHCORE_DATA_DIR': str(shared)}):
            with self.assertRaisesRegex(ValueError, 'removed'):
                self.query()

    def test_no_network_and_readonly_inputs(self):
        before = self.dbpath.read_bytes(), self.tif.read_bytes()
        with patch('socket.socket.connect', side_effect=AssertionError('Network forbidden')):
            self.query()
        self.assertEqual(before, (self.dbpath.read_bytes(), self.tif.read_bytes()))



    def test_real_local_vertical_grid_conversion(self):
        from pyproj import Transformer
        grid = self.root/'fixture.gtx'
        with rasterio.open(grid, 'w', driver='GTX', width=4, height=4, count=1, dtype='float32',
                           crs='EPSG:4326', transform=from_origin(-123, 39, 1, 1)) as dataset:
            dataset.write(np.full((4,4),20,dtype='float32'),1)
        operation = Transformer.from_pipeline('+proj=pipeline +step +proj=vgridshift +grids='+grid.as_posix()+' +multiplier=1')
        wrapped = SimpleNamespace(description='Synthetic constant geoid grid', transform=operation.transform,
                                  operations=[SimpleNamespace(grids=[SimpleNamespace(full_name=str(grid), available=True)])])
        self.values['pointing']['terrain_sources'] = [self.entry(vertical_crs='EPSG:5703')]
        self.save()
        actual = terrain.transformer
        with patch.object(terrain, 'transformer', side_effect=lambda source, target, lat, lon:
                          wrapped if getattr(source, 'is_compound', False) else actual(source, target, lat, lon)):
            self.assertAlmostEqual(self.query()['observer_height_wgs84_m'],70)

    def test_dependency_failure_and_w11_isolation(self):
        import builtins
        original = builtins.__import__
        def blocked(name, *args, **kwargs):
            if name.startswith(('skyfield','sgp4','rasterio')):
                raise ImportError('optional dependency blocked')
            return original(name, *args, **kwargs)
        output = io.StringIO()
        with patch('builtins.__import__',side_effect=blocked), redirect_stdout(output):
            pointing.main(['12345 37.5 -121.5'])
            self.assertEqual(catalog.lookup('sat','12345')['satellite']['norad_id'],12345)
        self.assertIn('dependency missing', output.getvalue())

    def test_unavailable_discovery_and_corrupt_catalog(self):
        from scripts.command_dependencies import dependency_status
        self.values['pointing']['terrain_sources'] = []
        self.save()
        self.assertTrue(dependency_status('!satpoint',True).startswith('Unavailable: GIS terrain'))
        self.values['pointing']['terrain_sources'] = [self.entry()]
        self.save()
        self.db.execute('PRAGMA user_version=99')
        self.db.commit()
        with self.assertRaisesRegex(ValueError,'schema'):
            self.query()

    def test_malformed_epoch_omm_convention_and_propagation_failure(self):
        self.db.execute("UPDATE orbits SET epoch='not-a-date'")
        self.db.commit()
        with self.assertRaisesRegex(ValueError,'timestamp'):
            self.query()
        self.orbit(elements=dict(self.elements,REF_FRAME='J2000'))
        with self.assertRaisesRegex(ValueError,'convention'):
            self.query()
        self.orbit()
        with patch.object(pointing,'angles',side_effect=ValueError('Orbit propagation failed')):
            with self.assertRaisesRegex(ValueError,'propagation failed'):
                self.query()

    def test_settings_generation_change_and_full_year_timestamp(self):
        original = pointing.angles
        def changed(*args):
            result=original(*args)
            self.values['orbit_max_age_days']=7
            self.save()
            return result
        with patch.object(pointing,'angles',side_effect=changed):
            with self.assertRaisesRegex(ValueError,'settings changed'):
                self.query()
        self.assertIn(self.now.strftime('%Y%m%dT'),pointing.render(self.query()))
        self.assertIn('WGS84 ellipsoid',pointing.lookup('help units')['message'])


    def test_fractional_orbit_identity_is_not_coerced(self):
        self.orbit(elements=dict(self.elements, NORAD_CAT_ID=12345.75))
        with self.assertRaisesRegex(ValueError, 'NORAD'):
            self.query()

    def test_embedded_vertical_datum_cannot_be_relabelled(self):
        self.raster(np.full((4,4),50.), crs='EPSG:4326+5703')
        with rasterio.open(self.tif, 'r+') as dataset:
            dataset.set_band_unit(1, 'm')
        self.values['pointing']['terrain_sources'] = [self.entry(vertical_crs='EPSG:4979')]
        self.save()
        with self.assertRaisesRegex(ValueError, 'vertical.*conflict|Conflicting.*vertical'):
            self.query()

    def test_freshness_uses_element_epoch_at_policy_boundaries(self):
        for epoch, recorded, reason in (
                (self.now+timedelta(seconds=.5), self.now, 'Future'),
                (self.now-timedelta(days=14, seconds=.5), self.now-timedelta(days=14), 'Stale')):
            self.orbit(elements=dict(self.elements,EPOCH=epoch.isoformat()), epoch=recorded)
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, reason):
                self.query()

    def test_large_compressed_blocks_are_rejected_before_decode(self):
        original = rasterio.open
        class HugeBlock:
            def __init__(self, dataset):
                self.dataset = dataset
            def __enter__(self):
                return self
            def __exit__(self, *args):
                self.dataset.close()
            def __getattr__(self, name):
                return getattr(self.dataset, name)
            @property
            def block_shapes(self):
                return [(100000,100000)]
            def read(self, *args, **kwargs):
                raise AssertionError('Oversized block reached raster decoder')
        with patch('rasterio.open',side_effect=lambda *args,**kwargs: HugeBlock(original(*args,**kwargs))):
            with self.assertRaisesRegex(ValueError,'block'):
                self.query()

    def test_source_identifiers_must_be_selectable_strings(self):
        self.values['pointing']['terrain_sources'][0]['id'] = 123
        self.save()
        with self.assertRaisesRegex(ValueError,'identity'):
            self.query()

    def test_rounded_azimuth_wraps_to_true_north(self):
        result = dict(self.query(), azimuth_true_deg=359.99)
        self.assertIn('azT=0.0deg',pointing.render(result))

    def test_explicit_terrain_selector_isolates_unavailable_other_sources(self):
        self.values['pointing']['terrain_sources'].append(self.entry(id='missing',path='missing.tif'))
        self.save()
        self.assertEqual(self.query('12345 37.5 -121.5 terrain dem')['terrain']['source_id'],'dem')
        from scripts.command_dependencies import dependency_status
        self.assertTrue(dependency_status('!satpoint',True).startswith('Partial:'))


    def test_matching_embedded_datum_and_native_metre_spelling(self):
        self.raster(np.full((4,4),50.), crs='EPSG:4326+5703')
        self.values['pointing']['terrain_sources'] = [self.entry(vertical_crs='EPSG:5703')]
        self.save()
        actual = terrain.transformer
        correction = SimpleNamespace(operations=[],description='fixture geoid',
                                     transform=lambda x,y,h,**kw: (x,y,h+20))
        with patch.object(terrain,'transformer',side_effect=lambda source,target,lat,lon:
                          correction if getattr(source,'is_compound',False) else actual(source,target,lat,lon)):
            self.assertEqual(self.query()['observer_height_wgs84_m'],70)

    def test_depth_datum_and_boolean_elements_are_rejected(self):
        self.values['pointing']['terrain_sources'] = [self.entry(vertical_crs='EPSG:5715')]
        self.save()
        with self.assertRaisesRegex(ValueError,'vertical CRS'):
            self.query()
        self.values['pointing']['terrain_sources'] = [self.entry()]
        self.save()
        self.orbit(elements=dict(self.elements, MEAN_MOTION=True))
        with self.assertRaisesRegex(ValueError,'numeric element'):
            self.query()
        for identity in (True, 12345.0, '12345.1'):
            with self.assertRaisesRegex(ValueError,'NORAD'):
                pointing.norad_number(identity)

    def test_survey_feet_remain_distinct_from_international_feet(self):
        with rasterio.open(self.tif,'r+') as dataset:
            dataset.set_band_unit(1,'US survey foot')
        self.values['pointing']['terrain_sources'] = [self.entry(units='us_survey_ft')]
        self.save()
        self.assertAlmostEqual(self.query()['observer_height_wgs84_m'],50*1200/3937)
        self.values['pointing']['terrain_sources'][0]['units'] = 'ft'
        self.save()
        with self.assertRaisesRegex(ValueError,'units'):
            self.query()

if __name__ == '__main__':
    unittest.main()
