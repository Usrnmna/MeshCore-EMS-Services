"""Deterministic W17 aggregation, CAP lifecycle, source bridges and radio contracts."""
import asyncio
import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import responder
from scripts import brief_lookup as b, brief_sources as s, weather_lookup, weather_source
from scripts import gauge_data, gauge_lookup, water_local, water_settings
from scripts.command_dependencies import dependency_status, is_bundled
from test_weather import Provider, forecast, NOW, stamp

ROOT = Path(__file__).resolve().parents[1]


def alert(key='A', sent=NOW-60, refs=None, **changes):
    """Create point-response CAP evidence; IDs, not names, establish identity."""
    props = dict(id=key, event='Flood Warning', sender='w-nws.webmaster@noaa.gov', status='Actual',
                 messageType='Alert', sent=stamp(sent), effective=stamp(sent), expires=stamp(NOW+3600),
                 severity='Severe', references=refs or [])
    props.update(changes)
    return dict(type='Feature', id='https://api.weather.gov/alerts/'+key, properties=props, geometry=None)


def reference(key, sent=NOW-60):
    return dict(identifier=key, sender='w-nws.webmaster@noaa.gov', sent=stamp(sent))


def collection(*features):
    return dict(type='FeatureCollection', features=list(features))


class AlertTests(unittest.TestCase):
    def test_exact_duplicates_are_deduplicated_but_same_titles_are_not(self):
        original=alert()
        result=s.alerts_from(collection(original,copy.deepcopy(original),alert('B')),NOW)
        self.assertEqual([r['id'] for r in result['items']],['A','B'])
        self.assertEqual(result['state'],'ok')

    def test_update_cancel_and_expired_revisions_do_not_resurrect_previous_alert(self):
        for message in ('Update','Cancel'):
            updated=alert('B',NOW-30,[reference('A')],messageType=message)
            result=s.alerts_from(collection(alert(),updated),NOW)
            self.assertEqual([r['id'] for r in result['items']],['B'] if message=='Update' else [])
            updated['properties']['expires']=stamp(NOW-1)
            self.assertEqual(s.alerts_from(collection(alert(),updated),NOW)['items'],[])

    def test_conflicting_identity_withheld_and_unrelated_alert_preserved(self):
        other=alert(event='Tornado Warning')
        result=s.alerts_from(collection(alert(),other,alert('B')),NOW)
        self.assertEqual([r['id'] for r in result['items']],['B'])
        self.assertEqual(result['state'],'partial')

    def test_reference_time_sender_conflicts_and_cycles_are_not_arbitrarily_resolved(self):
        cycle=alert('B',NOW-30,[reference('A',NOW-20)],messageType='Update')
        result=s.alerts_from(collection(alert(),cycle),NOW)
        self.assertEqual(result['state'],'partial')
        self.assertEqual(result['items'],[])
        bad=alert('B',NOW-30,[dict(reference('A'),sender='other')],messageType='Update')
        self.assertEqual(s.alerts_from(collection(alert(),bad),NOW)['state'],'partial')

    def test_priority_stable_and_no_title_deduplication(self):
        rows=[alert('A',severity='Moderate'),alert('B',severity='Extreme'),alert('C',severity='Extreme')]
        self.assertEqual([r['id'] for r in s.alerts_from(collection(*reversed(rows)),NOW)['items']],['B','C','A'])

    def test_invalid_future_expired_and_nonactual_evidence(self):
        for changes in (dict(sent=None),dict(sent=stamp(NOW+1)),dict(expires=stamp(NOW-120)),dict(status='Unknown')):
            record=alert();record['properties'].update(changes)
            self.assertEqual(s.alerts_from(collection(record),NOW)['state'],'partial')
        for changes in (dict(status='Test'),dict(effective=stamp(NOW+100)),dict(expires=stamp(NOW-1))):
            self.assertEqual(s.alerts_from(collection(alert(**changes)),NOW)['items'],[])

    def test_incomplete_and_excessive_collections(self):
        data=collection(alert());data['pagination']={'next':'unfollowed'}
        result=s.alerts_from(data,NOW)
        self.assertEqual(len(result['items']),1);self.assertEqual(result['state'],'partial')
        with self.assertRaises(ValueError):s.alerts_from(collection(*[alert()]*101),NOW)

    def test_authoritative_point_query_and_coverage_required(self):
        client=Mock()
        client.get.side_effect=[({'type':'Feature','properties':{'forecastZone':'CAZ001'}},NOW+1,True),
                                (collection(alert()),NOW+1,True)]
        self.assertEqual(len(s.alerts((37.5,-122),client,lambda:NOW)['items']),1)
        self.assertEqual(client.get.call_args.args,(s.heat_adv.NWS_ALERTS_URL,{'point':'37.5000,-122.0000','status':'actual'}))
        client.get.side_effect=[({'properties':{}},NOW+1,True)]
        with self.assertRaises(ValueError):s.alerts((0,0),client,lambda:NOW)


class BriefTests(unittest.TestCase):
    def setUp(self):
        self.now=NOW
        self.clock=lambda:self.now
        self.readers={c:Mock(return_value=s.result()) for c in s.CATEGORIES}
        self.clients=lambda:Mock(geocode=Mock(),deadline=time.monotonic()+8)

    def query(self,text='37.5 -122',**kwargs):
        return b.lookup(text,clock=self.clock,readers=self.readers,client_factory=self.clients,**kwargs)

    def test_forms_default_focused_and_single_resolution(self):
        with patch.object(b.heat_adv,'resolve_location',return_value=(37.5,-122)) as resolve:
            result=self.query('Sacramento CA')
        resolve.assert_called_once()
        self.assertEqual(result['selected'],list(s.CATEGORIES))
        for reader in self.readers.values():self.assertEqual(reader.call_args.args[0],(37.5,-122))
        result=self.query('water 37.5,-122')
        self.assertEqual(result['selected'],['water']);self.assertEqual(len(result['not_selected']),3)
        for text in ('95814','weather Sacramento CA','fire Sacramento','alerts 37 -122'):
            self.assertIsNotNone(b.parse(text))

    def test_invalid_inputs_and_help(self):
        for text in ('water','weather alerts 1 2','91 0','0 -181','0 nan','1 2\n','x'*151,'--json 1 2','alerts alerts 1 2'):
            with self.subTest(text=text),self.assertRaises(ValueError):b.parse(text)
        self.assertEqual(b.lookup('help'),{'help':True})

    def test_failures_do_not_discard_usable_alerts(self):
        self.readers['alerts'].return_value=s.alerts_from(collection(alert()),NOW)
        self.readers['weather'].side_effect=TimeoutError('provider')
        self.readers['fire'].side_effect=ValueError('private path')
        self.readers['water'].side_effect=ImportError('missing')
        result=self.query()
        self.assertEqual(len(result['categories']['alerts']['items']),1)
        self.assertEqual([result['categories'][c]['state'] for c in ('weather','fire','water')],['timeout','failed','unavailable'])
        text=b.render(result)
        self.assertIn('NWS',text);self.assertIn('not all-clear',text)
        self.assertNotIn('private',json.dumps(result))

    def test_slow_reader_abandoned_and_later_reader_runs(self):
        def slow(*args):
            time.sleep(.08)
            return s.result()
        self.readers['alerts'].side_effect=slow
        with patch.object(s,'CATEGORY_SECONDS',.02):
            result=self.query()
        self.assertEqual(result['categories']['alerts']['state'],'timeout')
        self.readers['weather'].assert_called_once()

    def test_unavailable_category_and_total_deadline(self):
        del self.readers['fire']
        self.assertEqual(self.query()['categories']['fire']['state'],'unavailable')
        budget=s.Budget()
        def exhaust(*args):
            budget.deadline=0
            return s.result()
        self.readers['alerts'].side_effect=exhaust
        result=self.query(budget=budget)
        self.assertEqual(result['categories']['weather']['state'],'not_checked')

    def test_request_exhaustion_is_distinct_from_provider_failure(self):
        self.readers['alerts'].side_effect=s.LimitReached('budget')
        self.readers['fire'].side_effect=Exception('adapter failure')
        result=self.query()
        self.assertEqual(result['categories']['alerts']['state'],'not_checked')
        self.assertEqual(result['categories']['fire']['state'],'failed')
        self.assertEqual(result['categories']['weather']['state'],'ok')

    def test_final_freshness_recheck(self):
        self.readers['alerts'].return_value=s.alerts_from(collection(alert(expires=stamp(NOW+1))),NOW)
        def advance(*args):
            self.now+=2
            return s.result()
        self.readers['water'].side_effect=advance
        result=self.query()
        self.assertEqual(result['categories']['alerts']['items'],[])
        self.assertEqual(result['categories']['alerts']['state'],'partial')

    def test_alert_revision_becoming_effective_during_briefing(self):
        for message in ('Update','Cancel'):
            self.now=NOW
            revision=alert('B',NOW-30,[reference('A')],messageType=message,effective=stamp(NOW+1))
            self.readers['alerts'].return_value=s.alerts_from(collection(alert(),revision),NOW)
            def advance(*args):
                self.now=NOW+2
                return s.result()
            self.readers['water'].side_effect=advance
            result=self.query()['categories']['alerts']
            self.assertEqual([r['id'] for r in result['items']],['B'] if message=='Update' else [])

    def test_malformed_category_cannot_discard_other_results(self):
        self.readers['alerts'].return_value=s.alerts_from(collection(alert()),NOW)
        for malformed in (dict(items=[]),s.result(items=[dict(kind='weather',data={})]),
                          s.result(items=[dict(kind='weather',data=float('nan'))])):
            self.readers['weather'].return_value=malformed
            with self.subTest(malformed=malformed):
                result=self.query()
                self.assertEqual(result['categories']['weather']['state'],'failed')
                self.assertEqual(len(result['categories']['alerts']['items']),1)
                json.dumps(result,allow_nan=False)

    def test_radio_whole_items_long_names_and_sender_tags(self):
        self.readers['alerts'].return_value=s.alerts_from(collection(alert(event='\u6e29'*100)),NOW)
        self.readers['water'].side_effect=ValueError('unavailable')
        result=self.query()
        for sender in ('Alice','a'*80,'\u6e29'*26):
            with patch.dict(os.environ,MESHCORE_SENDER=sender):
                text=b.render(result)
            self.assertLessEqual(len(('@'+sender+' '+text).encode()),150)
            self.assertIn('not all-clear',text)
            self.assertNotIn('\u6e29',text)
            self.assertIn('alert',text.lower())

    def test_empty_success_never_means_clear(self):
        text=b.render(self.query('alerts 37 -122'))
        self.assertIn('No matching',text);self.assertIn('alerts',text)
        self.assertIn('not all-clear',text);self.assertIn('at ',text)

    def test_focused_fire_and_water_preserve_followup_identity_when_they_fit(self):
        rows={'fire':dict(kind='fire',id='11111111-1111-4111-8111-111111111111',distance_miles=1),
              'water':dict(kind='water',id='USGS-001',distance_miles=1,eligible_readings=1)}
        for category,row in rows.items():
            data=dict(categories={category:s.result('partial',[row],['coverage limited'])},selected=[category],checked=NOW)
            with patch.dict(os.environ,MESHCORE_SENDER='Alice'):
                text=b.render(data)
            self.assertIn(row['id'],text)
            self.assertIn('not all-clear',text)
            self.assertLessEqual(len(('@Alice '+text).encode()),150)
            if category=='water':
                self.assertIn('not upstream',text);self.assertIn('live unchecked',text)

    def test_weather_bridge_uses_existing_selection_without_second_resolution(self):
        with tempfile.TemporaryDirectory() as directory:
            cache=weather_source.Cache(Path(directory)/'weather.sqlite3')
            provider=Provider(self.clock)
            with patch.object(weather_lookup,'Cache',return_value=cache),patch.object(weather_lookup.heat_adv,'resolve_location',side_effect=AssertionError('duplicate geocoding')):
                result=s.weather((37.5,-122),provider,self.clock)
                self.assertEqual(result['items'][0]['data']['delivery'],'live')
                text=b.render(dict(categories={'weather':result},selected=['weather'],checked=NOW))
                self.assertIn('65F',text);self.assertIn('20%',text);self.assertIn('mph',text)
                self.assertIn('forecast',text);self.assertIn('not all-clear',text)
                self.now+=70;provider.failure=TimeoutError('offline')
                result=s.weather((37.5,-122),provider,self.clock)
                self.assertEqual(result['state'],'partial')
                self.assertIn('provider failed',result['items'][0]['data']['delivery'])
                self.now+=400
                with self.assertRaises(ValueError):s.weather((37.5,-122),provider,self.clock)

    def test_cached_forecast_expiring_while_other_sources_run_is_withheld(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(weather_lookup,'Cache',return_value=weather_source.Cache(Path(directory)/'w.sqlite')):
                data=s.weather((37.5,-122),Provider(self.clock),self.clock)
                data['items'][0]['data']['delivery']='cached'
                data['items'][0]['data']['cache_expires']=NOW+1
                b.recheck({'weather':data},NOW+2)
                self.assertEqual(data['items'],[])
                self.assertEqual(data['state'],'partial')
                text=b.render(dict(categories={'weather':data},selected=['weather'],checked=NOW+2))
                self.assertIn('expired',text)
                self.assertNotIn('provider failed',text)

    def test_shared_transport_budget_includes_retries_and_preserves_url_restrictions(self):
        from urllib.error import HTTPError
        import io
        budget=s.Budget()
        opener=Mock();opener.open.side_effect=HTTPError('url',503,'busy',{},None)
        client=s.Client(budget,self.clock,opener)
        with self.assertRaises(HTTPError):client.get(s.weather_source.NWS+'/points/1,2')
        self.assertEqual(budget.requests,2)
        self.assertLessEqual(opener.open.call_args.kwargs['timeout'],3)
        for _ in range(s.MAX_REQUESTS-2):budget.reserve()
        with self.assertRaises(ValueError):s.Client(budget,self.clock).reserve()
        self.assertTrue(s.Client.allowed_url(s.weather_source.NWS+'/alerts/active'))
        self.assertFalse(weather_source.allowed_url(s.weather_source.NWS+'/alerts/active'))
        self.assertFalse(s.Client.allowed_url('https://evil.test/alerts/active'))

    def test_local_attempt_limit_does_not_spend_another_category_budget(self):
        budget=s.Budget()
        client=s.Client(budget,self.clock)
        for _ in range(weather_source.MAX_REQUESTS):client.reserve()
        with self.assertRaises(s.LimitReached):client.reserve()
        self.assertEqual(budget.requests,weather_source.MAX_REQUESTS)
        other=s.Client(budget,self.clock)
        for _ in range(s.MAX_REQUESTS-weather_source.MAX_REQUESTS):other.reserve()
        self.assertEqual(budget.requests,s.MAX_REQUESTS)

    def test_direct_service_registration_and_local_json(self):
        with tempfile.TemporaryDirectory() as directory:
            actual=time.time();provider=Provider(lambda:actual)
            cache=weather_source.Cache(Path(directory)/'weather_current.sqlite3')
            weather_lookup.lookup('37.5 -122',clock=lambda:actual,client=provider,cache=cache)
            env=dict(os.environ,MESHCORE_RUNTIME_DIR=directory)
            env.pop('MESHCORE_SENDER',None);env.pop('MESHCORE_REQUEST_ID',None)
            run=subprocess.run([sys.executable,str(ROOT/'scripts/brief.py'),'--json','weather','37.5','-122'],
                               env=env,capture_output=True,text=True,check=True,timeout=10)
            data=json.loads(run.stdout)
            self.assertEqual(data['categories']['weather']['items'][0]['data']['delivery'],'cached')
            blocked=subprocess.run([sys.executable,str(ROOT/'scripts/brief.py'),'--json','help'],
                                   env=dict(env,MESHCORE_REQUEST_ID='service'),capture_output=True,text=True,check=True,timeout=10)
            self.assertIn('local-only',blocked.stdout)
            config=json.loads((ROOT/'config.json').read_bytes())['responder']
            config['_runtime_directory']=directory
            spec=config['commands']['!brief']
            self.assertTrue(is_bundled('!brief',spec));self.assertEqual(spec['args'],[])
            request=dict(sender='Alice',channel_name='Test',channel_id='default',channel_index=3,id='brief-test',
                         phrase='!brief weather 37.5 -122',command='!brief',arguments=['weather 37.5 -122'])
            output,error=asyncio.run(responder.run_script(ROOT,spec,request,config))
            self.assertFalse(error);self.assertIn('not all-clear',output)
            self.assertIn('unverified',dependency_status('!brief'))


class WaterBridgeTests(unittest.TestCase):
    def test_installed_identity_quality_and_generation_errors(self):
        config=water_settings.validate({})
        stations={sid:dict(geometry=dict(type='Point',coordinates=[-122,37.5])) for sid in ('USGS-001','CA-001')}
        row=dict(parameter_code='00060',time_series_id='001-series',selection_status='primary_instantaneous_candidate',
                 time=stamp(NOW-60),unit_of_measure='ft^3/s',value=10,approval_status='Provisional',qualifier='estimated')
        client=Mock(deadline=time.monotonic()+8)
        with patch.object(water_settings,'load',return_value=config),patch.object(gauge_data,'load_inventory',return_value=(Path('custom'),{},stations)),patch.object(gauge_data,'load_observations',return_value={'USGS-001':[row]}),patch.object(water_local,'read_json',return_value={}):
            data=s.water((37.5,-122),client,lambda:NOW)
            self.assertEqual([r['id'] for r in data['items']],['CA-001','USGS-001'])
            self.assertEqual([r['eligible_readings'] for r in data['items']],[0,1])
            self.assertEqual(data['items'][1]['readings'][0]['qualifier'],'estimated')
            self.assertFalse(data['live_checked'])
            b.recheck({'water':data},NOW+config['reading_max_age']+1)
            self.assertEqual(data['items'][1]['eligible_readings'],0)
            with patch.object(gauge_data,'load_observations',side_effect=ValueError('incompatible generation')):
                data=s.water((37.5,-122),client,lambda:NOW)
                self.assertTrue(any('incompatible' in i for i in data['issues']))
                self.assertTrue(all(r['eligible_readings'] is None for r in data['items']))
                b.recheck({'water':data},NOW+10)
                self.assertTrue(all(r['eligible_readings'] is None for r in data['items']))
                text=b.render(dict(categories={'water':data},selected=['water'],checked=NOW))
                self.assertIn('unavailable',text)
                self.assertNotIn('0 eligible',text)

    def test_disabled_and_removed_water_do_not_become_empty_success(self):
        with patch.object(water_settings,'load',return_value=water_settings.validate({'enabled':False})):
            self.assertEqual(s.water((0,0),Mock(),lambda:NOW)['state'],'unavailable')
        with patch.object(gauge_data,'load_inventory',side_effect=ValueError('managed removal')):
            with self.assertRaises(ValueError):s.water((0,0),Mock(),lambda:NOW)

    def test_custom_paths_integrity_and_explicit_managed_removal(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            root=root/".."/root.name  # Exercise equivalent path spellings.
            config=water_settings.validate({'data_directory':str(root/'custom')})
            with patch.dict(os.environ,MESHCORE_DATA_DIR=str(root)):
                self.assertEqual(water_settings.collection(config),(root/'custom'/'usgs_water').resolve())
                (root/'datasets.json').write_text(json.dumps({'schema':1,'datasets':{'usgs_water':{'active':None}}}),encoding='utf-8')
                with self.assertRaises(FileNotFoundError):water_settings.collection(water_settings.validate({}))
            target=root/'artifact'
            target.write_bytes(b'changed')
            with self.assertRaises(ValueError):water_local.verify_file(target,{'byte_count':7,'sha256':'incorrect'})


class FireBridgeTests(unittest.TestCase):
    def test_acquisition_freshness_is_rechecked_after_other_categories(self):
        detail=dict(observed=NOW,acquisition=NOW-3599,freshness='recent',cache_stale=False,
                    cache_future=False,partial=False)
        data=s.result(items=[dict(kind='fire',details={'acreage':detail})],stale_after=3600,
                      sources=[dict(source='incidents',fetched=NOW-3599,stale=False,max_age=3600)])
        b.recheck({'fire':data},NOW+2)
        self.assertTrue(detail['cache_stale'])
        self.assertTrue(data['sources'][0]['stale'])
        self.assertTrue(detail['partial'])
        self.assertEqual(data['state'],'partial')

    def test_existing_cache_identity_provenance_perimeter_and_freshness(self):
        from scripts import wildfire_settings
        from scripts.wildfire_store import Store
        import test_wildfire as fixtures
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'wildfire.sqlite3'
            with Store(path,writable=True) as store:
                store.replace('zones',[fixtures.zone()],'zones',now=NOW)
                geometry=dict(type='Point',coordinates=[-120,40])
                store.replace('incidents',[fixtures.feature('1',dict(IrwinID=fixtures.GUID,IncidentName='Example',
                    IncidentSize=20,PercentContained=10,ModifiedOnDateTime_dt=(NOW-60)*1000),geometry)],'wfigs',now=NOW)
                store.replace('egp',[],'egp',now=NOW)
                store.replace('perimeters',[],'perimeters',now=NOW)
            with patch.dict(os.environ,MESHCORE_RUNTIME_DIR=directory):
                client=Mock(deadline=time.monotonic()+8)
                result=s.fire((40,-120),client,lambda:NOW)
                self.assertEqual(result['items'][0]['id'],fixtures.GUID)
                detail=result['items'][0]['details']
                self.assertEqual(detail['acreage']['value'],20)
                self.assertEqual(detail['acreage']['source'],'incidents')
                self.assertEqual(detail['acreage']['observed'],NOW-60)
                self.assertIsNone(detail['perimeter']['observed'])
                self.assertFalse(result['live_checked'])
                self.assertEqual(s.fire((0,0),client,lambda:NOW)['state'],'unavailable')
                stale=s.fire((40,-120),client,lambda:NOW+7200)
                self.assertEqual(stale['items'][0]['details']['acreage']['freshness'],'stale')
                self.assertEqual(stale['state'],'partial')
            with Store(path,writable=True) as store:store.fail('incidents','offline',now=NOW)
            with patch.dict(os.environ,MESHCORE_RUNTIME_DIR=directory):
                failed=s.fire((40,-120),Mock(deadline=time.monotonic()+8),lambda:NOW)
                self.assertTrue(failed['items'][0]['details']['acreage']['source_failed'])

    def test_absent_or_disabled_cache_is_not_empty_success(self):
        from scripts import wildfire_settings
        with patch.object(wildfire_settings,'load',return_value=wildfire_settings.validate({'enabled':False})):
            self.assertEqual(s.fire((0,0),Mock(),lambda:NOW)['state'],'unavailable')
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,MESHCORE_RUNTIME_DIR=directory):
            with self.assertRaises(Exception):s.fire((0,0),Mock(deadline=time.monotonic()+8),lambda:NOW)


if __name__=='__main__':
    unittest.main()
