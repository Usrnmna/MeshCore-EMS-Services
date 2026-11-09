"""W16 deterministic NWS selection, expiry, transport and command contracts."""
import asyncio
import copy
from contextlib import closing
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

import responder
from scripts import weather_lookup as w, weather_source as s
from scripts.command_dependencies import dependency_status, is_bundled

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 7, 20, tzinfo=timezone.utc).timestamp()


def stamp(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def point(x=10):
    base = f'{s.NWS}/gridpoints/MTR/{x},20/forecast'
    return {'properties': dict(gridId='MTR', gridX=x, gridY=20, timeZone='America/Los_Angeles',
                               forecast=base, forecastHourly=base + '/hourly')}


def period(now=NOW, hourly=False, **changes):
    result = dict(startTime=stamp(now-1800), endTime=stamp(now+(1800 if hourly else 41400)),
                  number=1, isDaytime=True, temperature=65, temperatureUnit='F', temperatureTrend=None,
                  probabilityOfPrecipitation={'unitCode':'wmoUnit:percent','value':20},
                  windSpeed='5 to 10 mph', windDirection='SW', windGust=None, shortForecast='Partly sunny')
    result.update(changes)
    return result


def forecast(now=NOW, hourly=False, **changes):
    props = dict(updateTime=stamp(now-3600), generatedAt=stamp(now-1800),
                 validTimes=stamp(now-86400)+'/P7D', units='us', periods=[period(now,hourly)])
    props.update(changes)
    return {'properties':props}


class Provider:
    """Exercise real lookup logic with deterministic endpoint-specific responses."""
    def __init__(self, clock):
        self.clock = clock
        self.point = point()
        self.period = forecast(clock())
        self.hourly = forecast(clock(), True)
        self.calls = []
        self.failure = None
        self.queue = []
        self.ttl = 300
        self.store = True
        self.geocode = Mock(return_value={'results':[dict(name='Sacramento', admin1='California',
            country_code='US', population=100, latitude=37.5, longitude=-122.0, postcodes=['95814'])]})

    def get(self, url, params=None):
        self.calls.append((url,params))
        if self.queue:
            value = self.queue.pop(0)
        elif self.failure:
            value = self.failure
        else:
            value = self.point if '/points/' in url else self.hourly if url.endswith('/hourly') else self.period
        if isinstance(value, Exception):
            raise value
        return copy.deepcopy(value), self.clock()+self.ttl, self.store


class WeatherTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.now = NOW
        self.clock = lambda: self.now
        self.cache = s.Cache(self.root/'weather_current.sqlite3')
        self.provider = Provider(self.clock)

    def query(self, text='37.5 -122'):
        return w.lookup(text, clock=self.clock, client=self.provider, cache=self.cache)

    def test_location_forms_and_single_resolution(self):
        for text in ('37.5 -122', '37.5,-122', '95814', 'Sacramento', 'Sacramento CA', 'hourly Sacramento California', 'wind 37.5 -122'):
            self.assertIsNotNone(w.parse(text))
        result = self.query('Sacramento CA')
        self.assertEqual(result['point'],'37.5000,-122.0000')
        self.provider.geocode.assert_called_once()
        self.assertEqual(len(self.provider.calls),2)

    def test_invalid_queries_and_missing_location(self):
        for text in ('nan 0','0 inf','91 0','0 -181','hourly','wind hourly Sacramento','hourly hourly 1 2',
                     '--json 1 2','https://example.test','1 2\n','\u00e9'*76,'0 0 wind'):
            with self.subTest(text=text), self.assertRaises(s.Unavailable):w.parse(text)
        self.provider.geocode.return_value={'results':[]}
        with self.assertRaisesRegex(s.Unavailable,'location unresolved'):self.query('Missing CA')
        self.assertEqual(self.provider.calls,[])

    def test_default_current_and_hourly_wind_periods(self):
        result=self.query()
        self.assertEqual(result['product'],'period');self.assertEqual(result['gap_seconds'],0)
        for mode in ('hourly','wind'):
            result=self.query(mode+' 37.5 -122')
            self.assertEqual(result['product'],'hourly')
            self.assertEqual((w.instant(result['end'])-w.instant(result['start'])).total_seconds(),3600)
        self.assertEqual(self.provider.calls[-1][1],{'units':'us'})

    def test_unsorted_expired_and_future_gap_selection(self):
        current=period()
        expired=period(startTime=stamp(NOW-86400),endTime=stamp(NOW))
        later=period(startTime=current['endTime'],endTime=stamp(NOW+60000))
        data=forecast(periods=[later,expired,current])
        self.assertEqual(w.selected(data,NOW,'period')['period'],current)
        data['properties']['periods']=[later,expired]
        self.assertGreater(w.selected(data,NOW,'period')['gap_seconds'],0)
        data['properties']['periods']=[expired]
        with self.assertRaises(s.Unavailable):w.selected(data,NOW,'period')

    def test_conflicting_periods_and_exact_duplicates(self):
        row=period()
        self.assertEqual(w.selected(forecast(periods=[row,copy.deepcopy(row)]),NOW,'period')['period'],row)
        for other in (period(temperature=90), period(startTime=stamp(NOW+10))):
            with self.assertRaisesRegex(s.Unavailable,'conflicting'):
                w.selected(forecast(periods=[row,other]),NOW,'period')

    def test_period_counts_horizon_and_duration_bounds(self):
        for rows in ([],[period()]*201,[period(startTime=stamp(NOW+200000),endTime=stamp(NOW+210000))],
                     [period(startTime=stamp(NOW),endTime=stamp(NOW))]):
            with self.assertRaises(s.Unavailable):w.selected(forecast(periods=rows),NOW,'period')
        with self.assertRaises(s.Unavailable):w.selected(forecast(),NOW,'hourly')

    def test_source_freshness_and_contradictory_times(self):
        for changes in (dict(updateTime=None),dict(updateTime='2026-11-07T19:00:00'),
                        dict(updateTime=stamp(NOW+1)),dict(updateTime=stamp(NOW-43201)),
                        dict(generatedAt=stamp(NOW+1)),dict(generatedAt=stamp(NOW-7200)),
                        dict(validTimes=stamp(NOW-86400)+'/PT1H')):
            with self.subTest(changes=changes),self.assertRaises(s.Unavailable):
                w.selected(forecast(**changes),NOW,'period')
        self.assertIsNone(w.selected(forecast(generatedAt=None),NOW,'period')['generated'])

    def test_field_units_missing_values_trends_and_probabilities(self):
        row=period(probabilityOfPrecipitation={'unitCode':'wmoUnit:percent','value':0},temperature=0)
        values,_=w.fields(row,'period')
        self.assertIn('high 0F',values);self.assertIn('precip chance 0%',values)
        row.update(isDaytime=False,temperatureTrend='rising',temperatureUnit='C')
        self.assertIn('low 0C rising',w.fields(row,'period')[0])
        row.update(temperature=None,windSpeed=None,windDirection=None,probabilityOfPrecipitation=None)
        values,_=w.fields(row,'hourly')
        self.assertTrue(values[0].startswith('temp unknown'));self.assertIn('precip chance unknown',values)
        self.assertIn('unknown',values[-1])
        for value in (-1,101,float('nan'),True):
            row['probabilityOfPrecipitation']={'unitCode':'wmoUnit:percent','value':value}
            self.assertIn('precip chance unknown',w.fields(row,'hourly')[0])

    def test_quantitative_units_ranges_and_qualifications(self):
        row=period(temperature={'unitCode':'wmoUnit:degF','value':65},
            windSpeed={'unitCode':'wmoUnit:km_h-1','minValue':5,'maxValue':12},
            windGust={'unitCode':'wmoUnit:m_s-1','value':15})
        text=';'.join(w.fields(row,'period')[0])
        for token in ('65F','5-12 km/h','gust 15 m/s'):self.assertIn(token,text)
        row['temperature']['qualityControl']='Q'
        self.assertIn('high unknown',w.fields(row,'period')[0])
        row['windSpeed']['unitCode']='unknown'
        self.assertIn('unknown',w.fields(row,'wind')[0][0])
        self.assertIsNone(w.wind_value('12 to 5 mph'))
        self.assertEqual(w.wind_value('calm'),'calm')
        row.update(windSpeed='calm',windDirection='VRB')
        self.assertIn('VRB calm',w.fields(row,'wind')[0][0])

    def test_conflicting_units_and_unsupported_precip_units_are_unknown(self):
        row=period(temperature={'unitCode':'wmoUnit:degC','value':20},temperatureUnit='F',
                   probabilityOfPrecipitation={'unitCode':'wmoUnit:mm','value':10})
        values,_=w.fields(row,'period')
        self.assertIn('high unknown',values)
        self.assertIn('precip chance unknown',values)
        self.assertIsNone(w.wind_value('9'*400+' mph'))

    def test_nullable_range_bounds_preserve_scalar_and_reject_conflicts(self):
        quantity = dict(unitCode='wmoUnit:percent', value=0, minValue=None, maxValue=None)
        self.assertEqual(w.quantity(quantity, {'wmoUnit:percent': '%'}, 0, 100), '0%')
        quantity.update(value=20, minValue=10, maxValue=30)
        self.assertEqual(w.quantity(quantity, {'wmoUnit:percent': '%'}, 0, 100), '10-30%')
        for changes in (dict(value=90), dict(value=None, maxValue=None)):
            with self.subTest(changes=changes):
                self.assertIsNone(w.quantity(dict(quantity, **changes), {'wmoUnit:percent': '%'}, 0, 100))

    def test_fresh_cache_and_query_time_expiry(self):
        self.assertEqual(self.query()['delivery'],'live')
        self.provider.failure=TimeoutError('offline')
        self.now+=30
        self.assertEqual(self.query()['delivery'],'cached')
        self.assertEqual(len(self.provider.calls),2)
        self.now+=40
        self.assertEqual(self.query()['delivery'],'cached; provider failed')
        self.now+=300
        with self.assertRaisesRegex(s.Unavailable,'no eligible cached'):self.query()

    def test_expired_period_not_reused_even_with_valid_cache_ttl(self):
        self.provider.period=forecast(periods=[period(endTime=stamp(NOW+10))])
        self.query();self.now+=11
        self.provider.failure=TimeoutError('offline')
        with self.assertRaises(s.Unavailable):self.query()

    def test_cached_fallback_rechecks_source_freshness_after_failure(self):
        self.provider.period=forecast(updateTime=stamp(NOW-43200+10),generatedAt=None)
        self.query();self.now+=70
        self.provider.failure=TimeoutError('offline')
        with self.assertRaises(s.Unavailable):self.query()

    def test_malformed_refresh_cannot_promote_prior_cache_to_live(self):
        self.query();self.now+=70
        self.provider.period=forecast(updateTime=None)
        with self.assertRaises(s.Unavailable):self.query()
        self.assertIsNone(self.cache.read('v1:37.5000,-122.0000:period:us',self.now))

    def test_changed_grid_cannot_fallback_to_old_forecast(self):
        self.query();self.now+=70
        self.provider.queue=[point(11),TimeoutError('offline')]
        with self.assertRaises(s.Unavailable):self.query()
        self.assertIsNone(self.cache.read('v1:37.5000,-122.0000:period:us',self.now))

    def test_obsolete_endpoint_reresolves_once(self):
        gone=HTTPError('https://api.weather.gov/gridpoints/MTR/10,20/forecast',404,'gone',{},None)
        self.provider.queue=[point(),gone,point(11),forecast()]
        self.assertIn('/11,20/',self.query()['endpoint'])
        self.assertEqual(len(self.provider.calls),4)

    def test_obsolete_cached_endpoint_cannot_fallback_after_resolution_failure(self):
        for code in (404, 410):
            with self.subTest(code=code):
                self.provider.queue=[]
                self.query()
                self.now+=70
                self.provider.queue=[point(),HTTPError('url',code,'gone',{},None),TimeoutError('offline')]
                with self.assertRaisesRegex(s.Unavailable,'no eligible cached'):
                    self.query()
                self.assertIsNone(self.cache.read('v1:37.5000,-122.0000:period:us',self.now))

    def test_repeated_obsolete_endpoint_and_unsupported_coverage(self):
        self.provider.queue=[point(),HTTPError('url',404,'gone',{},None),point(),HTTPError('url',404,'gone',{},None)]
        with self.assertRaises(s.Unavailable):self.query()
        self.assertEqual(len(self.provider.calls),4)
        self.provider.failure=HTTPError('url',404,'outside',{},None)
        with self.assertRaisesRegex(s.Unavailable,'outside supported'):self.query('0 0')

    def test_cache_isolation_by_coordinate_and_product(self):
        self.query();self.query('hourly 37.5 -122');self.query('38 -122')
        with closing(sqlite3.connect(self.cache.path)) as db, db:
            self.assertEqual(db.execute('SELECT count(*) FROM current').fetchone()[0],3)

    def test_cache_endpoint_mismatch_is_refetched(self):
        self.query()
        key='v1:37.5000,-122.0000:period:us'
        value=self.cache.read(key,self.now)
        value['url']='https://api.weather.gov/gridpoints/MTR/999,20/forecast'
        self.cache.write(key,value,self.now)
        self.assertEqual(self.query()['delivery'],'live')
        self.assertEqual(len(self.provider.calls),4)

    def test_malformed_cache_and_cache_io_failure_do_not_block_live_forecast(self):
        self.query()
        with closing(sqlite3.connect(self.cache.path)) as db, db:db.execute("UPDATE current SET body='invalid'")
        self.assertEqual(self.query()['delivery'],'live')
        cache=s.Cache(self.root/'blocked'/'weather.sqlite3')
        (self.root/'blocked').write_text('file')
        self.assertEqual(w.lookup('37.5 -122',clock=self.clock,client=self.provider,cache=cache)['delivery'],'live')

    def test_unreadable_cache_path_is_a_cache_miss(self):
        cache=s.Cache(Mock(exists=Mock(side_effect=PermissionError('unreadable'))))
        self.assertIsNone(cache.read('key',NOW))

    def test_no_store_and_expiry_prevent_reuse(self):
        self.provider.store=False
        self.query();self.query()
        self.assertEqual(len(self.provider.calls),4)
        self.provider.store=True;self.provider.ttl=1
        self.query();self.now+=2;self.query()
        self.assertEqual(len(self.provider.calls),8)

    def test_cache_has_no_history_and_enforces_row_cap(self):
        value=dict(key='x',retrieved=self.now,expires=self.now+100)
        self.cache.write('x',value,self.now)
        self.cache.write('x',dict(value,expires=self.now+101),self.now)
        with patch.object(s,'MAX_CACHE_ROWS',2):
            for key in ('a','b','c'):self.cache.write(key,dict(value,key=key),self.now)
        with closing(sqlite3.connect(self.cache.path)) as db, db:
            self.assertEqual(db.execute('SELECT count(*) FROM current').fetchone()[0],2)

    def test_invalid_mapping_and_provider_data_never_mean_clear(self):
        for change in (dict(forecast='https://evil.test/forecast'),dict(gridX=True),dict(timeZone='Invalid/Zone')):
            self.provider.point=point();self.provider.point['properties'].update(change)
            with self.assertRaises(w.FAILURES):self.query()
        self.provider.point=point();self.provider.period={'properties':{'periods':[]}}
        with self.assertRaises(s.Unavailable):self.query()

    def test_dst_transition_and_host_timezone_independence(self):
        now=datetime(2026,11,1,8,30,tzinfo=timezone.utc).timestamp()
        self.now=now;self.provider=Provider(self.clock)
        self.provider.hourly=forecast(now,True,periods=[period(now,True,
            startTime='2026-11-01T01:00:00-07:00',endTime='2026-11-01T01:00:00-08:00')])
        result=self.query('wind 37.5 -122')
        with patch.dict(os.environ,TZ='Asia/Tokyo',MESHCORE_TIMEZONE='UTC'):
            text=w.render(result)
        self.assertIn('PDT',text);self.assertIn('PST',text)

    def test_radio_limits_and_whole_qualifications(self):
        result=self.query('wind 37.5 -122')
        result['delivery']='cached; provider failed'
        for sender in ('Alice','a'*80,'\u6e29'*26):
            with patch.dict(os.environ,MESHCORE_SENDER=sender):
                text=w.render(result)
                self.assertLessEqual(len(('@'+sender+' '+text).encode()),150)
                if 'mph' in text:
                    self.assertIn('provider failed',text);self.assertIn('forecast',text);self.assertIn('upd',text)
        result['period']['shortForecast']='\u00e9'*200
        self.assertNotIn('\u00e9',w.render(result))

    def test_normal_radio_replies_include_values_and_complete_intervals(self):
        for mode in ('','hourly ','wind '):
            result=self.query(mode+'37.5 -122')
            result['delivery']='live'
            text=w.render(result)
            self.assertIn('forecast',text);self.assertIn('upd',text)
            self.assertIn('5 to 10 mph',text)
            if mode!='wind ':
                self.assertIn('65F',text);self.assertIn('precip chance 20%',text)
            self.assertLessEqual(len(('@Reader '+text).encode()),150)

    def test_missing_field_and_oversized_summary_do_not_become_benign(self):
        result=self.query()
        result['period'].update(temperature=None,windSpeed=None,shortForecast='Sunny '*100)
        text=w.render(result)
        self.assertNotIn('Sunny',text)
        self.assertTrue('unknown' in text or 'withheld' in text)

    def test_direct_service_help_registration_and_dependencies(self):
        actual=datetime.now(timezone.utc).timestamp()
        provider=Provider(lambda:actual)
        runtime=self.root/'runtime'
        cache=s.Cache(runtime/'weather_current.sqlite3')
        w.lookup('37.5 -122',clock=lambda:actual,client=provider,cache=cache)
        env=dict(os.environ,MESHCORE_RUNTIME_DIR=str(runtime))
        env.pop('MESHCORE_SENDER',None);env.pop('MESHCORE_REQUEST_ID',None)
        run=subprocess.run([sys.executable,str(ROOT/'scripts/weather.py'),'--json','37.5','-122'],
                           env=env,capture_output=True,text=True,timeout=15,check=True)
        self.assertEqual(json.loads(run.stdout)['delivery'],'cached')
        blocked=subprocess.run([sys.executable,str(ROOT/'scripts/weather.py'),'--json','37.5','-122'],
                               env=dict(env,MESHCORE_REQUEST_ID='service'),capture_output=True,text=True,timeout=15,check=True)
        self.assertIn('local-only',blocked.stdout)
        self.assertNotIn('"period"',blocked.stdout)
        config=json.loads((ROOT/'config.json').read_bytes())['responder']
        config['_runtime_directory']=str(runtime)
        spec=config['commands']['!weather']
        self.assertTrue(is_bundled('!weather',spec));self.assertEqual(spec['args'],[])
        request=dict(sender='Alice',channel_name='Test',channel_id='default',channel_index=3,id='w16',
                     phrase='!weather 37.5 -122',command='!weather',arguments=['37.5 -122'])
        output,error=asyncio.run(responder.run_script(ROOT,spec,request,config))
        self.assertFalse(error);self.assertIn('forecast',output.lower())
        self.assertIn('unverified',dependency_status('!weather'))
        with patch('zoneinfo.ZoneInfo',side_effect=ImportError('missing')):
            self.assertIn('Unavailable',dependency_status('!weather'))


class TransportTests(unittest.TestCase):
    def response(self, raw, **headers):
        response=io.BytesIO(raw);response.headers=headers
        return response

    def test_http_age_expiry_and_cache_control(self):
        self.assertEqual(s.http_expiry({'Cache-Control':'max-age=120','Age':'20'},NOW),(NOW+100,True))
        self.assertEqual(s.http_expiry({'Cache-Control':'no-store'},NOW),(NOW,False))
        self.assertEqual(s.http_expiry({'Cache-Control':'no-cache'},NOW),(NOW,True))
        for headers in ({'Age':'nan'},{'Age':'301'},{'Cache-Control':'max-age=bad'}):
            with self.assertRaises(s.Unavailable):s.http_expiry(headers,NOW)

    def test_http_date_and_expiry_are_distinct_from_source_times(self):
        expiry,store=s.http_expiry({'Date':'Sat, 07 Nov 2026 20:00:00 GMT',
                                   'Expires':'Sat, 07 Nov 2026 20:01:00 GMT'},NOW)
        self.assertEqual(expiry,NOW+60);self.assertTrue(store)
        with self.assertRaises(s.Unavailable):
            s.http_expiry({'Date':'Sat, 07 Nov 2026 21:00:00 GMT'},NOW)

    def test_expired_upstream_http_cache_is_not_a_live_response(self):
        for headers in ({'Cache-Control':'max-age=30','Age':'31'},
                        {'Age':'1','Expires':'Sat, 07 Nov 2026 19:59:00 GMT'}):
            with self.assertRaisesRegex(s.Unavailable,'expired HTTP'):
                s.http_expiry(headers,NOW)

    def test_url_allowlist_and_redirect_rejection(self):
        for url in ('http://api.weather.gov/points/1,2','https://api.weather.gov.evil/points/1,2',
                    'https://api.weather.gov@evil/points/1,2','https://api.weather.gov/points/1,2?x=1',
                    'https://api.weather.gov/alerts/active','https://api.weather.gov:443/points/1,2'):
            self.assertFalse(s.allowed_url(url))
        with self.assertRaises(s.Unavailable):s.NoRedirect().redirect_request(None,None,302,'',{},'https://evil.test')

    def test_response_size_json_shape_and_request_bounds(self):
        for raw in (b'x'*(s.MAX_BYTES+1),b'invalid',b'[]'):
            client=s.Client(clock=lambda:NOW,opener=Mock(open=Mock(return_value=self.response(raw))))
            with self.assertRaises(ValueError):client.get(s.NWS+'/points/1,2')
        opener=Mock();client=s.Client(opener=opener);client.requests=s.MAX_REQUESTS
        with self.assertRaises(s.Unavailable):client.get(s.NWS+'/points/1,2')
        opener.open.assert_not_called()

    def test_one_transient_retry_and_timeout_bound(self):
        opener=Mock()
        opener.open.side_effect=[HTTPError('url',503,'busy',{},None),self.response(b'{}')]
        client=s.Client(clock=lambda:NOW,opener=opener)
        self.assertEqual(client.get(s.NWS+'/points/1,2')[0],{})
        self.assertEqual(opener.open.call_count,2)
        self.assertLessEqual(opener.open.call_args.kwargs['timeout'],8)

    def test_retry_exhaustion_timeout_and_deadline_do_not_return_forecasts(self):
        opener=Mock()
        opener.open.side_effect=[HTTPError('url',503,'busy',{},None),HTTPError('url',503,'busy',{},None)]
        client=s.Client(clock=lambda:NOW,opener=opener)
        with self.assertRaises(HTTPError):client.get(s.NWS+'/points/1,2')
        self.assertEqual(opener.open.call_count,2)
        opener.open.side_effect=TimeoutError('offline')
        with self.assertRaises(TimeoutError):s.Client(opener=opener).get(s.NWS+'/points/1,2')
        client=s.Client(opener=Mock());client.deadline=0
        with self.assertRaises(s.Unavailable):client.get(s.NWS+'/points/1,2')
        client.opener.open.assert_not_called()


if __name__ == '__main__':
    unittest.main()
