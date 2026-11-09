"""Offline W13 event, input-pinning, numerical and package integration checks."""
import asyncio
import builtins
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
import io
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

import numpy as np
import responder
from scripts import satellite_lookup as catalog
from scripts import satellite_passes as passes
from scripts import satellite_pointing as pointing
from scripts import satellite_terrain as terrain
import test_satellite_pointing as pointing_tests
import test_satellite_lookup as lookup_tests


class EventTests(unittest.TestCase):
    @staticmethod
    def wave(t):
        """A triangular fixture with known threshold crossings and maximum."""
        return 30 - abs(t - 50)

    def test_complete_and_multiple_candidates(self):
        elevation = lambda t: self.wave(t % 100)
        result = passes.segments([(30, 0), (50, 1), (70, 2), (130, 0), (150, 1), (170, 2)], 200, 10, elevation, [100])
        self.assertEqual(len(result), 2)
        self.assertTrue(result[0]['complete_pass'])
        self.assertEqual((result[0]['start'], result[0]['peak'], result[0]['end']), (30, 50, 70))

    def test_ongoing_and_clipped_segments(self):
        result = passes.segments([(10, 1), (30, 2)], 50, 10, lambda t: self.wave(t+40))[0]
        self.assertEqual(result['start_kind'], 'window_start')
        self.assertEqual(result['peak_kind'], 'segment maximum')
        self.assertFalse(result['complete_pass'])
        result = passes.segments([(30, 0)], 40, 10, self.wave)[0]
        self.assertEqual(result['end_kind'], 'window_end')
        self.assertEqual(result['peak'], 40)

    def test_multiple_culminations_choose_highest(self):
        knots, heights = [0, 10, 20, 30, 40, 50, 60], [0, 10, 30, 20, 40, 10, 0]
        result = passes.segments([(10, 0), (20, 1), (40, 1), (50, 2)], 60, 10,
                                 lambda t: float(np.interp(t, knots, heights)), [30])[0]
        self.assertEqual(result['peak'], 40)
        self.assertEqual(result['peak_elevation_deg'], 40)

    def test_continuous_above_below_and_exact_threshold(self):
        self.assertEqual(passes.segments([], 100, 10, lambda t: 0), [])
        for height in (10, 30):
            result = passes.segments([], 100, 10, lambda t: height)[0]
            self.assertEqual(result['start_kind'], 'window_start')
            self.assertEqual(result['end_kind'], 'window_end')
            self.assertFalse(result['complete_pass'])

    def test_grazing_and_simultaneous_contact(self):
        curve = lambda t: 10 - ((t-50)/10)**2
        result = passes.segments([(50, 1)], 100, 10, curve)[0]
        self.assertEqual(result['start_kind'], 'grazing')
        self.assertEqual(result['start'], result['end'])
        # A contact does not establish a positive-duration above-threshold pass.
        result = passes.segments([(50, 1), (50, 0), (50, 2)], 100, 10, curve)[0]
        self.assertEqual(result['start'], result['end'])

    def test_exact_boundary_crossings_and_duplicates(self):
        result = passes.segments([(0, 0), (20, 1), (40, 2), (40, 2)], 40, 10, lambda t: self.wave(t+30))[0]
        self.assertTrue(result['complete_pass'])
        self.assertEqual(result['start'], 0)

    def test_bad_order_missing_peak_and_missing_crossings(self):
        cases = [[(50, 1), (30, 0)], [(30, 0), (70, 2)], [(50, 1), (70, 2)],
                 [(30, 0), (40, 0)], [(30, 8)], [(101, 0)], [(float('nan'), 1)]]
        for events in cases:
            with self.subTest(events=events), self.assertRaisesRegex(ValueError, 'incomplete'):
                passes.segments(events, 100, 10, self.wave)
        with self.assertRaisesRegex(ValueError, 'Missing threshold'):
            passes.segments([], 100, 10, self.wave)

    def test_missing_boundary_dip_detected_by_minimum(self):
        with self.assertRaisesRegex(ValueError, 'Missing threshold'):
            passes.segments([], 100, 10, lambda t: 0 if 20 < t < 30 else 30, [25])

    def test_event_and_result_limits(self):
        with patch.object(passes, 'MAX_EVENTS', 2), self.assertRaisesRegex(ValueError, 'Event limit'):
            passes.segments([(30, 0), (50, 1), (70, 2)], 100, 10, self.wave)
        with patch.object(passes, 'MAX_SEGMENTS', 0), self.assertRaisesRegex(ValueError, 'count limit'):
            passes.segments([], 100, 10, lambda t: 30)

    def test_short_pass_probes_remain_between_events(self):
        result = passes.segments([(30, 0), (30.1, 1), (30.2, 2)], 60, 10,
                                 lambda t: 11-10*abs(t-30.1))[0]
        self.assertTrue(result['complete_pass'])
        self.assertEqual(result['peak'], 30.1)
        self.assertAlmostEqual(result['end']-result['start'], .2)

    def test_exact_window_contacts_are_not_empty_or_inferred_crossings(self):
        result = passes.segments([], 60, 10, lambda t: 10+(t-60))[0]
        self.assertEqual(result['start'], 60)
        self.assertEqual(result['start_kind'], 'window_contact')
        self.assertEqual(result['end_kind'], 'window_contact')
        self.assertFalse(result['complete_pass'])
        result = passes.segments([(0, 2)], 60, 10, lambda t: 10-t)[0]
        self.assertEqual(result['start_kind'], 'window_contact')
        self.assertEqual(result['end'], 0)


class PassTests(unittest.TestCase):
    # Reuse fixture construction without inheriting the W12 test cases.
    orbit = pointing_tests.PointingTests.orbit
    raster = pointing_tests.PointingTests.raster
    entry = pointing_tests.PointingTests.entry
    save = pointing_tests.PointingTests.save

    def setUp(self):
        """Pin numerical fixtures and the in-process query clock to a fixed UTC date."""
        pointing_tests.PointingTests.setUp(self)
        self.now = datetime(2026, 11, 1, 0, 0, tzinfo=timezone.utc)
        self.epoch = self.now-timedelta(days=1)
        self.elements['EPOCH'] = self.epoch.isoformat()
        self.orbit()
        clock = patch.object(passes, 'datetime', wraps=datetime)
        mocked = clock.start()
        self.addCleanup(clock.stop)
        mocked.now.side_effect = lambda *args: self.now

    def query(self, text='12345 37.5 -121.5', now=None):
        return passes.lookup(text, now=now or self.now)

    def model(self):
        from skyfield.api import load
        timescale = load.timescale(builtin=True)
        with catalog.catalog() as (db, _):
            satellite = pointing.exact_satellite(db, 12345)
            (_, model, _), _ = pointing.choose_orbit(db, satellite, self.now, 14, None, timescale)
        return model, timescale

    def test_parse_defaults_selectors_and_invalid_inputs(self):
        self.assertEqual(passes.parse('12345 -90 180')['hours'], 24)
        self.assertEqual(passes.parse('12345 0 0 next24h min 0 agl 2 terrain dem orbit abc field peak')['min'], 0)
        for tail in ('hours 0', 'hours 25', 'hours nan', 'min -1', 'min 91', 'min inf',
                     'min 2 min 3', 'next24h hours 2', 'hours 2 next24h', 'field max', 'at tomorrow',
                     'agl -1', 'agl 1001', 'terrain ../x', 'orbit', 'next24h next24h'):
            with self.subTest(tail=tail), self.assertRaises(ValueError):
                passes.parse('12345 0 0 '+tail)
        for text in ('012345 0 0', '12345 nan 0', '12345 91 0', '12345 0 -181', '12345 0', 'x'*151, '12345 0 0\n'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                passes.parse(text)

    def test_configurable_default_threshold(self):
        self.values['pointing']['pass_min_elevation_deg'] = 90
        self.save()
        result = self.query()
        self.assertEqual(result['minimum_elevation_deg'], 90)
        self.assertIsNone(result['segment'])
        self.assertEqual(self.query('12345 37.5 -121.5 min 0')['minimum_elevation_deg'], 0)
        for bad in (True, -1, 91, '10', float('nan')):
            self.values['pointing']['pass_min_elevation_deg'] = bad
            self.save()
            with self.assertRaisesRegex(ValueError, 'default pass'):
                self.query()

    def test_exact_identity_unknown_lifecycle_and_conflicting_identity(self):
        with self.assertRaisesRegex(ValueError, 'not in installed'):
            self.query('12346 37.5 -121.5')
        self.db.execute("UPDATE satellites SET lifecycle='retired'")
        self.db.commit()
        with self.assertRaisesRegex(ValueError, 'lifecycle'):
            self.query()
        self.db.execute("UPDATE satellites SET lifecycle='in orbit',data_json=?", (json.dumps({'norad_id': 1}),))
        self.db.commit()
        with self.assertRaisesRegex(ValueError, 'Conflicting satellite'):
            self.query()

    def test_duplicate_norad_identity_is_not_selected(self):
        self.db.execute('INSERT INTO satellites VALUES(?,?,?,?,?)', ('sat2', 12345, 'Other', 'in orbit', '{}'))
        self.db.commit()
        with self.assertRaisesRegex(ValueError, 'Ambiguous NORAD'):
            self.query()

    def test_terrain_agl_and_no_network(self):
        before = self.dbpath.read_bytes(), self.tif.read_bytes()
        with patch('socket.socket.connect', side_effect=AssertionError('Network forbidden')):
            result = self.query('12345 37.5 -121.5 agl 20 terrain dem')
        self.assertEqual(result['observer_height_wgs84_m'], 70)
        self.assertEqual(result['terrain']['vertical_crs'], 'EPSG:4979')
        self.assertEqual(result['refraction'], 'none')
        self.assertIn('containing pixel', result['terrain']['sampling'])
        self.assertEqual(before, (self.dbpath.read_bytes(), self.tif.read_bytes()))

    def test_terrain_nodata_missing_and_disambiguation(self):
        self.values['pointing']['terrain_sources'].append(self.entry(id='second'))
        self.save()
        with self.assertRaisesRegex(ValueError, 'Select terrain'):
            self.query()
        self.query('12345 37.5 -121.5 terrain dem')
        self.raster(np.full((4, 4), -9999.))
        self.values['pointing']['terrain_sources'] = [self.entry()]
        self.save()
        with self.assertRaisesRegex(ValueError, 'NoData'):
            self.query()
        self.values['pointing']['terrain_sources'] = []
        self.save()
        with self.assertRaisesRegex(ValueError, 'terrain'):
            self.query()

    def test_reuses_vertical_conversion_and_unavailable_grid(self):
        # The W12 regression tests exercise a real local GTX conversion; this
        # contract check ensures W13 passes the resulting height to propagation.
        from contextlib import contextmanager
        @contextmanager
        def converted(*args):
            yield dict(source_id='dem', ellipsoid_height_m=70, vertical_crs='EPSG:5703')
        with patch.object(terrain, 'terrain', converted), patch.object(passes, 'search', return_value={'segment': None}) as search:
            result = self.query('12345 37.5 -121.5 agl 5')
            self.assertEqual(search.call_args.args[7], 75)
            self.assertEqual(result['observer_height_wgs84_m'], 75)
        with patch.object(terrain, 'terrain', side_effect=ValueError('Required local datum grid unavailable')):
            with self.assertRaisesRegex(ValueError, 'grid unavailable'):
                self.query()

    def test_orbit_missing_malformed_identity_future_and_stale(self):
        self.db.execute('DELETE FROM orbits')
        self.db.commit()
        with self.assertRaisesRegex(ValueError, 'No eligible'):
            self.query()
        self.orbit(elements=dict(self.elements, NORAD_CAT_ID=12346))
        with self.assertRaisesRegex(ValueError, 'NORAD'):
            self.query()
        self.orbit(elements=dict(self.elements, EPOCH='bad'))
        with self.assertRaisesRegex(ValueError, 'timestamp'):
            self.query()
        self.orbit()
        with self.assertRaisesRegex(ValueError, 'Future'):
            self.query(now=self.epoch-timedelta(seconds=1))
        with self.assertRaisesRegex(ValueError, 'Stale'):
            self.query(now=self.epoch+timedelta(days=15))

    def test_ambiguity_and_explicit_pinned_orbit(self):
        self.orbit(source='fixture:second')
        with self.assertRaisesRegex(ValueError, 'Select orbit'):
            self.query()
        selector = pointing.orbit_id(dict(source_url='fixture:second', format='OMM_JSON'))
        result = self.query('12345 37.5 -121.5 orbit '+selector)
        self.assertEqual(result['orbit_source'], 'fixture:second')
        self.assertEqual(result['orbit_id'], selector)
        with self.assertRaisesRegex(ValueError, 'Unknown or conflicting'):
            self.query('12345 37.5 -121.5 orbit unknown')

    def test_freshness_entire_window_and_solver_margin(self):
        with self.assertRaisesRegex(ValueError, 'requested window'):
            self.query(now=self.epoch+timedelta(days=13, hours=1))
        with self.assertRaisesRegex(ValueError, 'solver margin'):
            self.query(now=self.epoch+timedelta(days=13))
        with self.assertRaisesRegex(ValueError, 'solver margin'):
            self.query(now=self.epoch)
        result = self.query(now=self.epoch+timedelta(days=12))
        self.assertEqual(result['orbit_age_end_days'], 13)

    def test_propagation_work_batch_time_and_resolution_bounds(self):
        model, timescale = self.model()
        start = timescale.from_datetime(self.now)
        end = timescale.from_datetime(self.now+timedelta(days=1))
        for name, limit in (('MAX_SAMPLES', 1), ('MAX_BATCH', 1), ('SEARCH_SECONDS', -1), ('MAX_INITIAL_SAMPLES', 1)):
            with self.subTest(name=name), patch.object(passes, name, limit), self.assertRaisesRegex(ValueError, 'limit'):
                passes.search(model, timescale, self.now, self.now+timedelta(days=1), 14, 37.5, -121.5, 50, 10)
        guarded, _ = passes.guarded_orbit(model, start, end, 14)
        with patch.object(model, '_at', return_value=(np.zeros(3), np.zeros(3), None, 'decayed')):
            with self.assertRaisesRegex(ValueError, 'propagation failed'):
                guarded.at(start)
        with patch.object(model, '_at', return_value=(np.full(3, np.nan), np.zeros(3), None, None)):
            with self.assertRaisesRegex(ValueError, 'propagation failed'):
                guarded.at(start)

    def test_actual_ongoing_clipped_and_no_pass(self):
        full = self.query()['segment']
        self.assertIsNotNone(full)
        middle = pointing.utc(full['peak'])
        underway = self.query(now=middle)['segment']
        self.assertEqual(underway['start_kind'], 'window_start')
        self.assertEqual(underway['peak_kind'], 'segment maximum')
        # End a minimum-length window shortly before the established maximum.
        clipped = self.query('12345 37.5 -121.5 hours 0.25', now=middle-timedelta(minutes=15, seconds=30))['segment']
        self.assertEqual(clipped['end_kind'], 'window_end')
        result = self.query('12345 37.5 -121.5 min 90')
        self.assertTrue(result['search_complete'])
        self.assertIsNone(result['segment'])
        self.assertIn('no pass', passes.render(result))

    def test_settings_terrain_and_catalog_changes_rejected(self):
        actual = passes.search
        for changed in ('settings', 'terrain', 'catalog'):
            def change(*args):
                result = actual(*args)
                if changed == 'settings':
                    self.values['orbit_max_age_days'] = 13
                    self.save()
                elif changed == 'terrain':
                    with self.tif.open('ab') as file:
                        file.write(b'changed')
                else:
                    stat = self.dbpath.stat()
                    os.utime(self.dbpath, ns=(stat.st_atime_ns, stat.st_mtime_ns+1000000))
                return result
            with self.subTest(changed=changed), patch.object(passes, 'search', side_effect=change):
                with self.assertRaises(ValueError):
                    self.query()
            if changed == 'terrain':
                self.values['pointing']['terrain_sources'] = [self.entry()]
                self.save()

    def test_explicit_removal_and_integrity_schema(self):
        self.db.execute('PRAGMA user_version=99')
        self.db.commit()
        with self.assertRaisesRegex(ValueError, 'schema'):
            self.query()
        self.db.execute('PRAGMA user_version=1')
        self.db.commit()
        self.values['pointing']['terrain_sources'][0]['sha256'] = '0'*64
        self.save()
        with self.assertRaisesRegex(ValueError, 'integrity'):
            self.query()
        self.values['pointing']['terrain_sources'] = [self.entry()]
        shared = self.root/'data'
        shared.mkdir()
        self.values['database'] = str(shared/'satellites/satellites.sqlite3')
        self.save()
        (shared/'datasets.json').write_text(json.dumps({'schema': 1, 'datasets': {'satellites': {'active': None}}}), encoding='utf-8')
        with patch.dict(os.environ, {'MESHCORE_DATA_DIR': str(shared)}), self.assertRaisesRegex(ValueError, 'removed'):
            self.query()

    def test_managed_generations_dependencies_and_switch_during_search(self):
        lookup_tests.SatelliteTests.managed(self)
        self.values['database'] = str(self.root/'satellites/satellites.sqlite3')
        self.save()
        receipt = json.loads(self.receipt.read_bytes())
        with patch.dict(os.environ, {'MESHCORE_DATA_DIR': str(self.root)}):
            self.assertTrue(self.query()['search_complete'])
            for key, value in (('dataset', 'wrong'), ('dependencies', {'other': {}}), ('path', 'wrong')):
                self.receipt.write_text(json.dumps(dict(receipt, **{key: value})), encoding='utf-8')
                with self.subTest(key=key), self.assertRaises(ValueError):
                    self.query()
            self.receipt.write_text(json.dumps(receipt), encoding='utf-8')
            actual = passes.search
            def switched(*args):
                result = actual(*args)
                self.registry.write_text(json.dumps({'schema': 1, 'datasets': {'satellites': {'active': None}}}), encoding='utf-8')
                return result
            with patch.object(passes, 'search', side_effect=switched), self.assertRaisesRegex(ValueError, 'removed'):
                self.query()

    def test_radio_fields_qualifications_and_utf8_limits(self):
        result = self.query()
        for field in (None, 'start', 'peak', 'end', 'window'):
            text = passes.render(dict(result, field=field))
            self.assertIn('pred', text)
            self.assertIn('geom', text)
            self.assertIn('GIS:dem', text)
            self.assertIn('AGL=0m', text)
            self.assertIn('orb<=', text)
            self.assertIn('RF/sightline unverified', text)
            for sender in ('Reader', '\u00e9'*40):
                with patch.dict(os.environ, {'MESHCORE_SENDER': sender}):
                    self.assertLessEqual(len(('@'+sender+' '+passes.render(dict(result, field=field))).encode()), 150)
        long = dict(result, terrain=dict(result['terrain'], source_id='a'*12), partial_orbit_coverage=True)
        text = passes.render(long)
        self.assertTrue('partial sources' in text or 'too long' in text)

    def test_utc_rollover_and_partial_peak_label(self):
        result = self.query()
        segment = dict(result['segment'], start='2026-12-31T23:59:30Z', peak='2027-01-01T00:00:30Z', end='2027-01-01T00:01:30Z')
        text = passes.render(dict(result, segment=segment))
        self.assertTrue('too long' in text or ('20261231T' in text and '20270101T' in text))
        segment.update(complete_pass=False, start_kind='window_start', end_kind='window_end')
        text = passes.render(dict(result, segment=segment, field='peak'))
        if 'too long' not in text:
            self.assertIn('segmax', text)
            self.assertIn('ongoing', text)
            self.assertIn('clipped', text)
        equivalent = self.query(now=self.now.astimezone(timezone(timedelta(hours=-8))))
        self.assertEqual(result['window_start'], equivalent['window_start'])

    def test_boundary_contact_radio_preserves_qualification(self):
        result = self.query()
        instant = result['window_end']
        segment = dict(start=instant, end=instant, peak=instant, start_kind='window_contact',
                       end_kind='window_contact', complete_pass=False, peak_elevation_deg=10)
        for field in (None, 'start', 'peak', 'end'):
            text = passes.render(dict(result, segment=segment, field=field))
            self.assertIn('boundary contact', text)
            self.assertNotIn('no pass', text)
            self.assertNotIn('max=', text)
            self.assertIn('GIS:dem', text)
            self.assertIn('RF/sightline unverified', text)
            self.assertLessEqual(len(('@Reader '+text).encode()), 150)

    def test_direct_service_discovery_registration_and_local_json(self):
        from scripts.command_dependencies import is_bundled, dependency_status
        root = Path(__file__).resolve().parents[1]
        config = json.loads((root/'config.json').read_bytes())['responder']
        spec = config['commands']['!satpass']
        self.assertEqual(spec['script'], 'scripts/satpass.py')
        self.assertEqual(spec['args'], [])
        self.assertTrue(is_bundled('!satpass', spec))
        # Fresh subprocesses use the real clock; keep only their fixture orbit
        # current without making the numerical/reference cases date-dependent.
        self.now = datetime.now(timezone.utc).replace(microsecond=0)
        self.epoch = self.now-timedelta(days=1)
        self.elements['EPOCH'] = self.epoch.isoformat()
        self.orbit()
        direct = subprocess.run([sys.executable, str(root/spec['script']), '--json', '12345', '37.5', '-121.5'],
                                capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(direct.returncode, 0, direct.stderr)
        self.assertEqual(json.loads(direct.stdout)['observer_height_wgs84_m'], 50)
        request = dict(sender='Alice', channel_name='Test', channel_id='default', channel_index=3, id='w13',
                       phrase='!satpass 12345 37.5 -121.5 field start', command='!satpass', arguments=['12345 37.5 -121.5 field start'])
        output, diagnostic = asyncio.run(responder.run_script(root, spec, request, config))
        self.assertFalse(diagnostic)
        self.assertIn('hW84=50.0m', output)
        self.assertLessEqual(len(responder.reply_parts('Alice', output, max_parts=1)[0].encode()), 150)
        request.update(command='!help', arguments=['!satpass'], phrase='!help !satpass')
        output, diagnostic = asyncio.run(responder.run_script(root, config['commands']['!help'], request, config))
        self.assertFalse(diagnostic)
        self.assertIn('Partial', output)
        output = io.StringIO()
        with redirect_stdout(output), patch.dict(os.environ, {'MESHCORE_REQUEST_ID': 'service'}):
            passes.main(['--json', '12345 37.5 -121.5'])
        self.assertIn('local-only', output.getvalue())
        self.values['pointing']['terrain_sources'] = []
        self.save()
        self.assertTrue(dependency_status('!satpass', True).startswith('Unavailable: GIS terrain'))

    def test_optional_import_failure_preserves_w11(self):
        original = builtins.__import__
        def blocked(name, *args, **kwargs):
            if name.startswith(('skyfield', 'sgp4', 'rasterio')):
                raise ImportError('optional dependency blocked')
            return original(name, *args, **kwargs)
        output = io.StringIO()
        with patch('builtins.__import__', side_effect=blocked), redirect_stdout(output):
            passes.main(['12345 37.5 -121.5'])
            self.assertEqual(catalog.lookup('sat', '12345')['satellite']['norad_id'], 12345)
        self.assertIn('dependency missing', output.getvalue())

    def test_discovery_reports_missing_datum_dependency(self):
        from scripts.command_dependencies import dependency_status
        original = builtins.__import__
        def blocked(name, *args, **kwargs):
            if name == 'pyproj':
                raise ImportError('datum dependency blocked')
            return original(name, *args, **kwargs)
        with patch('builtins.__import__', side_effect=blocked):
            self.assertTrue(dependency_status('!satpass', True).startswith('Unavailable:'))

    def test_incomplete_search_is_not_rendered_as_no_pass(self):
        output = io.StringIO()
        with patch.object(passes, 'search', side_effect=ValueError('Search limit reached; prediction incomplete')), redirect_stdout(output):
            passes.main(['--json', '12345 37.5 -121.5'])
        result = json.loads(output.getvalue())
        self.assertIn('incomplete', result['error'])
        self.assertNotIn('segment', result)
        self.assertNotIn('no pass', output.getvalue())

    def test_enabled_unavailable_discovery_remains_distinct_from_disabled(self):
        self.values['pointing']['terrain_sources'] = []
        self.save()
        program = Path(__file__).resolve().parents[1]/'scripts/command_help.py'
        for allowed, expected in (({'!satpass': True}, 'Unavailable'), ({}, 'unavailable on this channel')):
            result = subprocess.run([sys.executable, str(program), '!satpass'],
                                    env=dict(os.environ, MESHCORE_HELP_COMMANDS=json.dumps(allowed)),
                                    capture_output=True, text=True, encoding='utf-8', timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(expected, result.stdout)

    def test_partially_eligible_orbit_inventory_remains_qualified(self):
        self.orbit(source='fixture:bad', elements=dict(self.elements, NORAD_CAT_ID=2))
        result = self.query('12345 37.5 -121.5 field start')
        self.assertTrue(result['partial_orbit_coverage'])
        self.assertIn('partial sources', passes.render(result))

    def test_independent_sgp4_enu_crossings_and_peak(self):
        # Fixed UTC case through a DST-transition date. Independent SGP4/GMST,
        # WGS84 ECEF and ENU calculation, with grid bracketing and bisection;
        # neither Skyfield event search nor its observer transform is reused.
        from sgp4.api import Satrec, jday
        from sgp4 import omm
        from sgp4.propagation import gstime
        self.now = datetime(2026, 11, 1, 0, 0, tzinfo=timezone.utc)
        self.epoch = self.now-timedelta(days=1)
        self.elements['EPOCH'] = self.epoch.isoformat()
        self.orbit()
        model = Satrec()
        omm.initialize(model, dict(self.elements, EPOCH=self.epoch.strftime('%Y-%m-%dT%H:%M:%S.%f')))
        lat, lon = map(math.radians, (37.5, -121.5))
        eccentricity = 6.6943799901413165e-3
        radius = 6378137/math.sqrt(1-eccentricity*math.sin(lat)**2)
        observer = np.array([(radius+50)*math.cos(lat)*math.cos(lon), (radius+50)*math.cos(lat)*math.sin(lon),
                             (radius*(1-eccentricity)+50)*math.sin(lat)])
        def elevation(seconds):
            date = self.now+timedelta(seconds=seconds)
            jd, fraction = jday(date.year, date.month, date.day, date.hour, date.minute, date.second+date.microsecond/1e6)
            error, position, _ = model.sgp4(jd, fraction)
            self.assertEqual(error, 0)
            theta = gstime(jd+fraction)
            x, y, z = position
            fixed = np.array([math.cos(theta)*x+math.sin(theta)*y, -math.sin(theta)*x+math.cos(theta)*y, z])*1000
            delta = fixed-observer
            east = np.dot([-math.sin(lon), math.cos(lon), 0], delta)
            north = np.dot([-math.sin(lat)*math.cos(lon), -math.sin(lat)*math.sin(lon), math.cos(lat)], delta)
            up = np.dot([math.cos(lat)*math.cos(lon), math.cos(lat)*math.sin(lon), math.sin(lat)], delta)
            return math.degrees(math.atan2(up, math.hypot(east, north)))
        brackets = []
        previous = elevation(0) >= 10
        for stamp in range(10, 86401, 10):
            above = elevation(stamp) >= 10
            if above != previous:
                brackets.append((stamp-10, stamp, above))
            previous = above
        self.assertGreaterEqual(len(brackets), 2)
        crossings = []
        for left, right, rising in brackets[:2]:
            for _ in range(25):
                middle = (left+right)/2
                if (elevation(middle) >= 10) == rising:
                    right = middle
                else:
                    left = middle
            crossings.append((left+right)/2)
        left, right = crossings
        for _ in range(40):
            a, b = (2*left+right)/3, (left+2*right)/3
            if elevation(a) < elevation(b):
                left = a
            else:
                right = b
        peak = (left+right)/2
        result = self.query()['segment']
        for key, expected in zip(('start', 'peak', 'end'), (crossings[0], peak, crossings[1])):
            actual = (pointing.utc(result[key])-self.now).total_seconds()
            self.assertAlmostEqual(actual, expected, delta=1.0)
        self.assertAlmostEqual(result['peak_elevation_deg'], elevation(peak), delta=.05)


if __name__ == '__main__':
    unittest.main()
