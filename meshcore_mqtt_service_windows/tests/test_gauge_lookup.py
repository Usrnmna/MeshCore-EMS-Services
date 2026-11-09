"""Exact gauge identity, latest observations, proximity and radio contracts."""
import json
import os
import subprocess
import sys
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from scripts import gauge_lookup as g, water_settings
import responder

NOW = 1792500000

def row(series='001', **changes):
    """Provide a source-shaped observation whose age is evaluated at query time."""
    value = dict(time_series_id=series, parameter_code='00065', time=datetime.fromtimestamp(NOW-60,timezone.utc).isoformat(), value='2.5', unit_of_measure='ft', approval_status='Provisional', qualifier='estimated', selection_status='primary_instantaneous_candidate')
    return dict(value, **changes)

class GaugeTests(unittest.TestCase):
    def setUp(self):
        self.config = water_settings.validate({'noaa_enabled':False})
        self.stations = {'USGS-001':{'geometry':{'type':'Point','coordinates':[-122,38]},'properties':{}},'CA001-001':{'geometry':{'type':'Point','coordinates':[-122.01,38]},'properties':{}}}
        self.values = {'USGS-001':[row()]}
        for target, value in [('load_inventory',(Path('fixture'),{},self.stations)),('load_observations',self.values)]:
            p=patch.object(g.gauge_data,target,return_value=value);p.start();self.addCleanup(p.stop)
        p=patch.object(g.water_local,'read_json',return_value={});p.start();self.addCleanup(p.stop)

    def lookup(self,text,command='gauge'):
        return g.lookup(command,text,self.config,NOW)

    def test_exact_identity_and_collision(self):
        self.assertIn('Provisional estimated',self.lookup('USGS-001 stage'))
        self.assertIn('not found',self.lookup('USGS-1'))
        self.assertIn('readings unavailable',self.lookup('CA001-001'))
        self.assertIn('snapshot',self.lookup('USGS-001 source'))

    def test_series_selection_is_exact_and_never_arbitrary(self):
        self.values['USGS-001'].append(row('002'))
        self.assertIn('ambiguous',self.lookup('USGS-001 stage'))
        self.assertIn('2.5 ft',self.lookup('USGS-001 stage series 002'))
        self.assertIn('unavailable',self.lookup('USGS-001 series 2'))
        self.values['USGS-001'].append(row('002'))
        self.assertIn('ambiguous',self.lookup('USGS-001 series 002'))

    def test_freshness_units_and_activity_are_recomputed(self):
        for changes,state in [({'time':datetime.fromtimestamp(NOW-90000,timezone.utc).isoformat()},'stale'),({'time':datetime.fromtimestamp(NOW+60,timezone.utc).isoformat()},'future'),({'unit_of_measure':'m'},'unexpected_units'),({'value':'nan'},'invalid'),({'selection_status':'inactive'},'ineligible')]:
            with self.subTest(state=state):
                self.values['USGS-001'][:]=[row(**changes)]
                self.assertIn(state,self.lookup('USGS-001'))

    def test_flow_and_stage_are_separate(self):
        self.values['USGS-001'].append(row('flow',parameter_code='00060',unit_of_measure='ft^3/s'))
        self.assertIn('ambiguous',self.lookup('USGS-001'))
        self.assertIn('flow 2.5 ft^3/s',self.lookup('USGS-001 flow'))

    def test_missing_timestamp_and_boolean_values_are_invalid(self):
        for changes in ({'time': None}, {'value': True}):
            with self.subTest(changes=changes):
                reading = dict(row(), kind='stage', **changes)
                result = g.qualify(reading, NOW, 60)
                self.assertFalse(result['usable'])
                self.assertIn('invalid', result['state'])

    def test_activity_does_not_hide_freshness_or_unit_errors(self):
        reading = dict(row(time=datetime.fromtimestamp(NOW-90000,timezone.utc).isoformat(),
                           unit_of_measure='m'), kind='stage', inactive=True)
        result = g.qualify(reading, NOW, 60)
        for state in ('inactive', 'stale', 'unexpected_units'):
            self.assertIn(state, result['state'])
        self.assertFalse(result['usable'])

    def test_live_failure_keeps_snapshot_qualification(self):
        self.config['noaa_enabled']=True
        with patch.object(g.gauge_data, 'station_link', return_value='ABCDE'), patch.object(g,'live_rows',side_effect=ValueError('offline')):
            result=self.lookup('USGS-001 stage')
        self.assertIn('snapshot',result)
        self.assertIn('live failed',result)
        self.assertNotIn('NOAA live',result)

    def test_nearby_ranks_inventory_without_upstream_inference(self):
        result=self.lookup('near 38 -122 2','gauges')
        self.assertIn('not upstream',result)
        self.assertIn('USGS-001',result)
        self.assertIn('snapshot reading',result)
        self.values.clear()
        self.assertIn('inventory only',self.lookup('near 38 -122 2','gauges'))
        self.assertIn('No inventory',self.lookup('near 0 0 1','gauges'))

    def test_query_bounds(self):
        for command,text in [('gauge','USGS-001\n'),('gauge','USGS-001 --settings x'),('gauges','near nan 0'),('gauges','near 91 0'),('gauges','near 38 -122 51'),('gauges','near 38 -122 0')]:
            with self.subTest(text=text),self.assertRaises(ValueError):g.parse(command,text)

    def test_radio_never_truncates_qualifications(self):
        for sender in ('Alice','a'*80,'温'*26):
            with patch.dict(os.environ,{'MESHCORE_SENDER':sender}):
                text=responder.reply_parts(sender,self.lookup('USGS-001'),max_parts=1)[0]
                self.assertLessEqual(len(text.encode()),150)
                if '2.5' in text:
                    self.assertIn('Provisional estimated',text)
                    self.assertIn('snapshot',text)

    def test_live_adapter_requires_review_and_retains_source(self):
        self.config['noaa_enabled']=True
        with patch.object(g.water_identifiers,'load',return_value=({},'')),patch.object(g.water_sources,'gauge') as adapter:
            self.assertEqual(g.live_rows('USGS-001',self.config,NOW)[0],[])
            adapter.assert_not_called()
        review={'USGS-001':{'identity_status':'matched','lid':'ABCDE'}}
        payload={'in_service':True,'observation':{'primary':3,'primaryUnit':'ft','validTime':row()['time'],'qualifier':'estimated'}}
        with patch.object(g.water_identifiers,'load',return_value=(review,'')),patch.object(g.water_sources,'gauge',return_value=payload) as adapter:
            rows,state=g.live_rows('USGS-001',self.config,NOW)
            adapter.assert_called_once_with('ABCDE','USGS-001',self.config,NOW)
            self.assertEqual(rows[0]['series'],'nwps-primary')
            self.assertEqual(rows[0]['qualifier'],'estimated')
            self.assertTrue(rows[0]['usable'])
            payload['in_service']=False
            self.assertFalse(g.live_rows('USGS-001',self.config,NOW)[0][0]['usable'])

    def test_review_cannot_override_conflicting_inventory_link(self):
        self.config['noaa_enabled'] = True
        review = {'USGS-001': {'identity_status': 'matched', 'lid': 'ABCDE'}}
        with patch.object(g.water_identifiers, 'load', return_value=(review, '')), patch.object(g.water_sources, 'gauge') as adapter:
            rows, state = g.live_rows('USGS-001', self.config, NOW, 'OTHER')
            self.assertEqual(rows, [])
            self.assertIn('unavailable', state)
            adapter.assert_not_called()

    def test_cli_and_registered_literal_arguments(self):
        root=Path(__file__).resolve().parents[1]
        commands=json.loads((root/'config.json').read_bytes())['responder']['commands']
        for command in ('gauge','gauges'):
            spec=commands['!'+command]
            self.assertEqual(spec['script'],f'scripts/{command}.py')
            self.assertEqual(spec['args'],[])
            self.assertEqual(responder.match_command('!'+command+' help',commands),('!'+command,['help'],None))
            result=subprocess.run([sys.executable,str(root/spec['script']),'help'],capture_output=True,text=True,timeout=15)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('!'+command,result.stdout)



class InstalledFixtureTests(unittest.TestCase):
    def test_custom_path_generations_direct_and_service_context(self):
        import csv
        import gzip
        import hashlib
        import tempfile
        from scripts import gauge_data
        def publish(root, kind, files, **metadata):
            folder=root/kind;folder.mkdir()
            entries={}
            for name,raw in files.items():
                (folder/name).write_bytes(raw)
                entries[name]={'byte_count':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
            raw=json.dumps(dict(kind=kind,complete=True,files=entries,**metadata)).encode()
            (folder/'manifest.json').write_bytes(raw)
            pointer={'manifest_path':kind+'/manifest.json','byte_count':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
            (root/(kind+'.json')).write_text(json.dumps(pointer))
            return pointer
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);root=base/'usgs_water';root.mkdir()
            station={'type':'Feature','id':'USGS-001','properties':{'agency_code':'USGS','monitoring_location_number':'001'},'geometry':{'type':'Point','coordinates':[-122,38]}}
            pointer=publish(root,'inventory',{'stations.geojson.gz':gzip.compress(json.dumps({'type':'FeatureCollection','features':[station]}).encode())})
            import io
            out=io.StringIO();data=dict(row(),station_id='USGS-001');writer=csv.DictWriter(out,fieldnames=list(data));writer.writeheader();writer.writerow(data)
            publish(root,'observations',{'series_conditions.csv':out.getvalue().encode(),'latest_measurements.csv':b'fixture\n'},inventory_pointer=pointer)
            config=water_settings.validate({'data_directory':str(base),'noaa_enabled':False})
            self.assertIn('USGS-001',g.lookup('gauges','near 38 -122',config,NOW))
            self.assertIn('Provisional estimated',g.lookup('gauge','USGS-001 stage',config,NOW))
            package=Path(__file__).resolve().parents[1]
            environment=dict(os.environ,MESHCORE_WATER_SETTINGS=json.dumps(config),PYTHONIOENCODING='utf-8')
            result=subprocess.run([sys.executable,str(package/'scripts/gauge.py'),'USGS-001','stage'],env=environment,cwd=base,capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('snapshot',result.stdout)
            self.assertIn('Provisional estimated',result.stdout)
            import asyncio
            service_config=json.loads((package/'config.json').read_bytes())['responder']
            service_config['water']=config
            request=dict(sender='Alice', channel_name='Test', channel_id='default', channel_index=3,
                         id='gauge-fixture', phrase='!gauge USGS-001 stage', command='!gauge',
                         arguments=['USGS-001 stage'])
            output, diagnostic=asyncio.run(responder.run_script(package,service_config['commands']['!gauge'],request,service_config))
            self.assertFalse(diagnostic)
            self.assertIn('Provisional estimated',output)
            # A valid checksum does not make a malformed observation valid. Its
            # exact series and quality remain available for an explicit lookup.
            data['time'] = 'not-a-timestamp'
            out = io.StringIO()
            writer = csv.DictWriter(out, fieldnames=list(data))
            writer.writeheader()
            writer.writerow(data)
            observation_folder = root / 'observations'
            raw = out.getvalue().encode()
            (observation_folder / 'series_conditions.csv').write_bytes(raw)
            manifest_path = observation_folder / 'manifest.json'
            manifest = json.loads(manifest_path.read_bytes())
            manifest['files']['series_conditions.csv'] = {'byte_count': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
            raw = json.dumps(manifest).encode()
            manifest_path.write_bytes(raw)
            (root / 'observations.json').write_text(json.dumps({'manifest_path': 'observations/manifest.json',
                'byte_count': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}))
            result = g.lookup('gauge', 'USGS-001 stage series 001', config, NOW)
            self.assertIn('invalid time', result)
            self.assertIn('Provisional estimated', result)
            (root/'observations'/'series_conditions.csv').write_text('damaged')
            self.assertIn('snapshot unavailable',g.lookup('gauge','USGS-001',config,NOW))

if __name__ == "__main__":
    unittest.main()
