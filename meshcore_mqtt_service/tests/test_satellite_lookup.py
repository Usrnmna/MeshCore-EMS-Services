"""Satellite catalog identity, lifecycle, freshness and command integration tests."""
import hashlib
import io
import shutil
from contextlib import redirect_stdout
import asyncio
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import responder
from scripts import satellite_lookup as s

SCHEMA = """
-- Each operation is a documented capability, never a fabricated matrix cell.
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS satellites (
    satellite_id TEXT PRIMARY KEY,
    norad_id INTEGER,
    name TEXT NOT NULL,
    lifecycle TEXT,
    data_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS satellite_norad ON satellites(norad_id);
CREATE TABLE IF NOT EXISTS operations (
    operation_id TEXT PRIMARY KEY,
    satellite_id TEXT NOT NULL REFERENCES satellites(satellite_id),
    name TEXT NOT NULL,
    data_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS operations_by_satellite ON operations(satellite_id);
CREATE TABLE IF NOT EXISTS operation_scopes (
    operation_id TEXT NOT NULL REFERENCES operations(operation_id),
    scope TEXT NOT NULL,
    PRIMARY KEY(operation_id, scope)
);
CREATE TABLE IF NOT EXISTS operation_versions (
    version_id TEXT PRIMARY KEY,
    operation_id TEXT NOT NULL REFERENCES operations(operation_id),
    recorded_at TEXT NOT NULL,
    data_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS versions_by_operation ON operation_versions(operation_id);
CREATE TABLE IF NOT EXISTS observations (
    observation_id TEXT PRIMARY KEY,
    operation_id TEXT NOT NULL REFERENCES operations(operation_id),
    status TEXT NOT NULL CHECK(status IN ('active','inactive','scheduled_off','unknown')),
    observed_at TEXT NOT NULL,
    source_url TEXT NOT NULL,
    note TEXT NOT NULL,
    evidence_kind TEXT NOT NULL,
    recorded_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS observations_by_operation ON observations(operation_id, observed_at DESC);
CREATE TABLE IF NOT EXISTS reception_reports (
    report_id TEXT PRIMARY KEY,
    operation_id TEXT REFERENCES operations(operation_id),
    satellite_label TEXT NOT NULL,
    mode_label TEXT NOT NULL,
    reported_status TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    source_url TEXT NOT NULL,
    data_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS reports_by_operation ON reception_reports(operation_id);
CREATE TABLE IF NOT EXISTS orbits (
    satellite_id TEXT NOT NULL REFERENCES satellites(satellite_id),
    source_url TEXT NOT NULL,
    format TEXT NOT NULL,
    epoch TEXT,
    fetched_at TEXT NOT NULL,
    data_json TEXT NOT NULL,
    PRIMARY KEY(satellite_id, source_url, format)
);
CREATE TABLE IF NOT EXISTS source_fetches (
    url TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    PRIMARY KEY(url, fetched_at, sha256)
);
CREATE TABLE IF NOT EXISTS refresh_runs (
    run_id INTEGER PRIMARY KEY,
    completed_at TEXT NOT NULL,
    report_json TEXT NOT NULL
);

-- Status freshness is evaluated at query time, so offline data ages honestly.
DROP VIEW IF EXISTS operation_reference;
CREATE VIEW operation_reference AS
SELECT o.operation_id, o.satellite_id, s.norad_id, s.name AS satellite_name,
       s.lifecycle, o.name AS operation_name,
       json_extract(o.data_json, '$.source_reported_status') AS catalog_status,
       json_extract(o.data_json, '$.source_updated_at') AS catalog_updated_at,
       json_extract(o.data_json, '$.present_in_latest_source') AS present_in_latest_source,
       CASE
         WHEN s.lifecycle IN ('decayed','re-entered','future','not launched') THEN 'unknown'
         WHEN e.observation_id IS NULL THEN 'unknown'
         WHEN (SELECT COUNT(DISTINCT status) FROM observations AS conflicting
               WHERE conflicting.operation_id=o.operation_id
               AND julianday(conflicting.observed_at)=julianday(e.observed_at)) > 1 THEN 'unknown'
         WHEN julianday(e.observed_at) > julianday('now') THEN 'unknown'
         WHEN julianday('now') - julianday(e.observed_at) >
           CAST((SELECT value FROM metadata WHERE key='status_max_age_days') AS REAL) THEN 'unknown'
         ELSE e.status
       END AS current_status,
       e.status AS last_evidence_status, e.observed_at AS evidence_at,
       (SELECT COUNT(DISTINCT status) FROM observations AS conflicting
        WHERE conflicting.operation_id=o.operation_id
        AND julianday(conflicting.observed_at)=julianday(e.observed_at)) > 1 AS conflicting_evidence,
       e.source_url AS status_source, e.note AS status_note, e.evidence_kind,
       o.data_json
FROM operations o JOIN satellites s USING(satellite_id)
LEFT JOIN observations e ON e.observation_id = (
  SELECT observation_id FROM observations
  WHERE operation_id=o.operation_id
  ORDER BY julianday(observed_at) DESC, recorded_at DESC, observation_id DESC LIMIT 1
);
"""

class SatelliteTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name); self.folder = self.root / 'catalog'; self.folder.mkdir()
        self.dbpath = self.folder / 'satellites.sqlite3'
        self.db = sqlite3.connect(self.dbpath); self.addCleanup(self.db.close)
        self.db.executescript(SCHEMA); self.db.execute('PRAGMA user_version=1')
        self.db.execute("INSERT INTO metadata VALUES('status_max_age_days','30')")
        for sid, nid, name in [('a',123,'Test'),('b',456,'Other')]:
            self.db.execute('INSERT INTO satellites VALUES(?,?,?,?,?)',(sid,nid,name,'in orbit',json.dumps({'aliases':['Alias'], 'satellite_id':sid})))
        self.op('one','a'); self.db.commit()
        (self.root/'satellite-settings.json').write_text(json.dumps({'database':str(self.dbpath)}),encoding='utf-8')
        (self.root/'config.json').write_text('{}',encoding='utf-8')
        p=patch.object(s,'ROOT',self.root);p.start();self.addCleanup(p.stop)

    def op(self, oid, sid, **extra):
        data=dict(operation_id=oid,satellite_id=sid,source_reported_status='active',present_in_latest_source=True,
                  modulation='FM',protocols=[],scopes=['beacon'],downlink_low_hz=145800000.125,downlink_high_hz=145800000.125)
        data.update(extra)
        self.db.execute('INSERT OR REPLACE INTO operations VALUES(?,?,?,?)',(oid,sid,'Beacon',json.dumps(data)))
        self.db.commit()

    def query(self,text='123',command='satfreq'):
        return s.lookup(command,text)

    def test_identity_names_alias_collision_unknown(self):
        self.assertEqual(self.query('name Test','sat')['satellite']['norad_id'],123)
        self.assertIn('Ambiguous',self.query('name Alias','sat')['message'])
        self.assertIn('Not in',self.query('999','sat')['message'])
        for text in ('0123','-123','1.2','123 extra','x'*151):
            with self.assertRaises(ValueError):self.query(text)
        self.db.execute("UPDATE satellites SET norad_id=123 WHERE satellite_id='b'");self.db.commit()
        self.assertIn('Ambiguous',self.query('123')['message'])

    def test_operation_selection_and_cross_satellite(self):
        self.op('two','a');self.op('foreign','b')
        self.assertIn('select op',s.render(self.query()))
        self.assertEqual(len(self.query('123 op two')['operations']),1)
        self.assertIn('unavailable',s.render(self.query('123 op foreign')))

    def test_freshness_conflicts_missing_future(self):
        row=dict(conflicting_evidence=0,evidence_at=None,current_status='active')
        now=datetime.now(timezone.utc)
        self.assertIn('no evidence',s.status(row,30,now))
        for days,label in [(31,'stale'),(-1,'future'),(1,'active')]:
            row['evidence_at']=(now-timedelta(days=days)).isoformat()
            self.assertIn(label,s.status(row,30,now))
        row['conflicting_evidence']=1;self.assertIn('conflict',s.status(row,30,now))
        row.update(conflicting_evidence=0,evidence_at='2026-01-01');self.assertIn('undated',s.status(row,30,now))

    def test_catalog_active_does_not_become_evidence(self):
        self.assertIn('no evidence',self.query()['operations'][0]['evaluated_status'])
        self.assertIn('RF unverified',s.render(self.query('123','sat')))
        self.assertEqual(self.query()['operations'][0]['catalog_status'],'active')

    def test_lifecycle_and_operation_inactive_are_separate(self):
        # SQLite's wall clock can lag Python's by a clock tick on Windows.
        # This case checks lifecycle separation, not the future-evidence boundary.
        stamp=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
        self.db.execute('INSERT INTO observations VALUES(?,?,?,?,?,?,?,?)',('obs','one','inactive',stamp,'source','confirmed','confirmed_failure',stamp));self.db.commit()
        self.assertTrue(self.query()['operations'][0]['evaluated_status'].startswith('inactive'))
        self.assertEqual(self.query()['satellite']['lifecycle'],'in orbit')
        for lifecycle in ('retired','decommissioned','re-entered','future'):
            self.db.execute('UPDATE satellites SET lifecycle=? WHERE satellite_id=?',(lifecycle,'a'));self.db.commit()
            self.assertIn('withheld',self.query()['message'])

    def test_frequency_precision_roles_and_no_invention(self):
        r=self.query('123 op one field downlink');text=s.render(r)
        self.assertIn('145800000.125Hz',text)
        self.assertIn('TX auth unknown',text)
        self.assertNotIn('up=',text)
        self.assertIn('up=?Hz',s.render(self.query('123 op one field uplink')))
        self.op('one','a',downlink_low_hz=None,downlink_high_hz=None,uplink_low_hz=145000000,protocols=['AX.25'])
        self.assertIn('up=145000000Hz',s.render(self.query('123 op one field uplink')))
        self.assertEqual(self.query()['operations'][0]['attributes']['protocols'],['AX.25'])
        for number in (-1,float('nan'),float('inf')):
            with self.assertRaises(ValueError):s.frequency(number)

    def test_passband_and_source_qualifications_retained(self):
        self.op('one','a',passband_width_hz=20000,inverting=True,review_required=True,schedule='scheduled',superseded_by='replacement',present_in_latest_source=False)
        result=self.query('123 op one field passband')
        self.assertEqual(result['operations'][0]['attributes']['passband_width_hz'],20000)
        self.assertIn('discontinued/superseded',s.render(result))
        self.assertNotIn('Hz', s.render(result))

    def test_radio_limits_and_invalid_selectors(self):
        for sender in ('Reader','é'*40):
            with patch.dict(os.environ,{'MESHCORE_SENDER':sender}):
                for text in ('123','123 op one field downlink','help'):
                    out=s.render(self.query(text));self.assertLessEqual(len(('@'+sender+' '+out).encode()),150)
        with self.assertRaises(ValueError):self.query('123 field invented')
        with self.assertRaises(ValueError):self.query('123\n')

    def test_schema_integrity_and_freshness_policy(self):
        self.db.execute('PRAGMA user_version=99');self.db.commit()
        with self.assertRaisesRegex(ValueError,'schema'):self.query()
        self.db.execute('PRAGMA user_version=1');self.db.execute("UPDATE metadata SET value='nan'");self.db.commit()
        with self.assertRaises(ValueError):self.query()

    def test_managed_removal_and_custom_path(self):
        self.assertEqual(self.query()['satellite']['norad_id'],123)
        (self.root/'satellite-settings.json').write_text(json.dumps({'database':str(self.root/'satellites/satellites.sqlite3')}),encoding='utf-8')
        (self.root/'datasets.json').write_text(json.dumps({'schema':1,'datasets':{'satellites':{'active':None}}}),encoding='utf-8')
        with patch.dict(os.environ,{'MESHCORE_DATA_DIR':str(self.root)}):
            with self.assertRaisesRegex(ValueError,'removed'):self.query()

    def test_readonly_and_generation_change(self):
        before=self.dbpath.read_bytes();self.query();self.assertEqual(before,self.dbpath.read_bytes())
        with s.catalog() as (db, age):
            with self.assertRaises(sqlite3.OperationalError):db.execute('DELETE FROM satellites')

    def test_direct_and_service_commands_without_tracking(self):
        root=Path(__file__).resolve().parents[1]
        config=json.loads((root/'config.json').read_bytes())['responder']
        for command in ('sat','satfreq'):
            spec=config['commands']['!'+command]
            self.assertEqual(spec['script'],'scripts/'+command+'.py');self.assertEqual(spec['args'],[])
            direct=subprocess.run([sys.executable,str(root/spec['script']),'help'],capture_output=True,text=True,timeout=10)
            self.assertEqual(direct.returncode,0,direct.stderr)
            request=dict(sender='Alice',channel_name='Test',channel_id='default',channel_index=3,id='w11',phrase='!'+command+' help',command='!'+command,arguments=['help'])
            output,diagnostic=asyncio.run(responder.run_script(root,spec,request,config))
            self.assertFalse(diagnostic);self.assertEqual(output.strip(),direct.stdout.strip())
        # Tracking independence is checked in a fresh import-blocking subprocess below.


    def managed(self):
        """Publish a fixture with the same immutable receipt layout as the installer."""
        content = self.root / '.datasets/satellites/g1/content'
        content.mkdir(parents=True, exist_ok=True)
        target = content / 'satellites.sqlite3'
        shutil.copyfile(self.dbpath, target)
        active = {'path': '.datasets/satellites/g1/content',
                  'receipt': '.datasets/satellites/g1/receipt.json'}
        receipt = dict(schema=1, dataset='satellites', path=active['path'], dependencies={},
                       files={'satellites.sqlite3': {'bytes': target.stat().st_size,
                              'sha256': hashlib.sha256(target.read_bytes()).hexdigest()}})
        self.registry = self.root / 'datasets.json'
        self.receipt = content.parent / 'receipt.json'
        self.registry.write_text(json.dumps({'schema': 1, 'datasets': {'satellites': {'active': active}}}), encoding='utf-8')
        self.receipt.write_text(json.dumps(receipt), encoding='utf-8')
        (self.root / 'satellite-settings.json').write_text(json.dumps({'database': str(self.root / 'satellites/satellites.sqlite3')}), encoding='utf-8')
        return target

    def test_managed_hash_dependency_and_generation_identity(self):
        target = self.managed()
        with patch.dict(os.environ, {'MESHCORE_DATA_DIR': str(self.root)}):
            self.assertEqual(self.query()['satellite']['norad_id'], 123)
            receipt = json.loads(self.receipt.read_bytes())
            for key, value, error in [('dataset', 'other', 'generation'), ('dependencies', {'other': {}}, 'dependencies'),
                                      ('path', 'other', 'generation')]:
                bad = dict(receipt, **{key: value})
                self.receipt.write_text(json.dumps(bad), encoding='utf-8')
                with self.assertRaisesRegex(ValueError, error):
                    self.query()
            self.receipt.write_text(json.dumps(receipt), encoding='utf-8')
            target.write_bytes(target.read_bytes() + b'corruption')
            with self.assertRaisesRegex(ValueError, 'integrity'):
                self.query()

    def test_generation_switch_during_read_is_rejected(self):
        self.managed()
        with patch.dict(os.environ, {'MESHCORE_DATA_DIR': str(self.root)}):
            with self.assertRaisesRegex(ValueError, 'removed'):
                with s.catalog():
                    self.registry.write_text(json.dumps({'schema': 1, 'datasets': {'satellites': {'active': None}}}), encoding='utf-8')

    def test_explicit_managed_path_cannot_bypass_receipts_or_removal(self):
        target = self.managed()
        (self.root / 'satellite-settings.json').write_text(json.dumps({'database': str(target)}), encoding='utf-8')
        with patch.dict(os.environ, {'MESHCORE_DATA_DIR': str(self.root)}):
            self.assertEqual(self.query()['satellite']['norad_id'], 123)
            self.registry.write_text(json.dumps({'schema': 1, 'datasets': {'satellites': {'active': None}}}), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'removed'):
                self.query()

    def test_shared_root_config_and_missing_catalog(self):
        target = self.managed()
        (self.root / 'config.json').write_text(json.dumps({'dataset_root': str(self.root)}), encoding='utf-8')
        self.assertEqual(self.query()['satellite']['norad_id'], 123)
        target.unlink()
        with self.assertRaises(OSError):
            self.query()

    def test_missing_policy_and_structured_errors(self):
        self.db.execute('DELETE FROM metadata'); self.db.commit()
        with self.assertRaisesRegex(ValueError, 'freshness policy'):
            self.query()
        output = io.StringIO()
        with redirect_stdout(output):
            s.main('sat', ['--json', '123'])
        self.assertIn('freshness policy', json.loads(output.getvalue())['error'])

    def test_satellite_and_operation_identity_conflicts(self):
        self.op('one', 'a', satellite_id='wrong')
        with self.assertRaisesRegex(ValueError, 'operation identity'):
            self.query()
        self.op('one', 'a')
        self.db.execute("UPDATE satellites SET data_json=? WHERE satellite_id='a'", (json.dumps({'satellite_id': 'b'}),))
        self.db.commit()
        with self.assertRaisesRegex(ValueError, 'satellite identity'):
            self.query()

    def observation(self, oid, status, stamp):
        """Insert dated evidence without changing the source catalog status."""
        self.db.execute('INSERT INTO observations VALUES(?,?,?,?,?,?,?,?)',
                        (oid, 'one', status, stamp, 'fixture-source', 'fixture evidence', {'inactive': 'confirmed_failure', 'scheduled_off': 'operator_schedule'}.get(status, 'confirmed'), stamp))
        self.db.commit()

    def test_observations_queried_again_and_conflicts(self):
        now = datetime.now(timezone.utc)
        stamp = (now - timedelta(days=2)).isoformat()
        self.observation('old', 'active', stamp)
        self.assertTrue(self.query()['operations'][0]['evaluated_status'].startswith('active@'))
        with patch.object(s, 'datetime', wraps=datetime) as clock:
            clock.now.return_value = now + timedelta(days=31)
            self.assertIn('stale', self.query()['operations'][0]['evaluated_status'])
        self.observation('conflict', 'inactive', stamp)
        self.assertIn('conflict', self.query()['operations'][0]['evaluated_status'])
        self.observation('scheduled', 'scheduled_off', (now - timedelta(days=1)).isoformat())
        self.assertTrue(self.query()['operations'][0]['evaluated_status'].startswith('scheduled_off'))

    def test_stale_catalog_and_discontinued_operation(self):
        self.op('one', 'a', source_reported_status='inactive', source_updated_at='2000-01-01T00:00:00Z')
        self.assertIn('cat=inactive@2000-01-01(stale)', s.render(self.query('123 field status')))
        self.op('old', 'a', superseded_by='one')
        self.assertEqual([r['operation_id'] for r in self.query()['operations']], ['one'])
        text = s.render(self.query('123 op old field downlink'))
        self.assertIn('discontinued/superseded', text)
        self.assertNotIn('Hz', text)
        self.assertEqual(self.db.execute('SELECT count(*) FROM operations').fetchone()[0], 2)

    def test_result_limit_and_stable_selection(self):
        for n in range(25):
            self.op('op%02d' % n, 'a', downlink_low_hz=140000000+n)
        result = self.query()
        self.assertTrue(result['partial'])
        self.assertEqual(len(result['operations']), 20)
        self.assertIn('partial', s.render(result))
        self.assertEqual(self.query('123 op op24')['operations'][0]['operation_id'], 'op24')

    def test_passband_modulation_and_missing_direction(self):
        self.op('one', 'a', scopes=['two_way_voice'], transmitter_type='Transponder',
                modulation='USB', protocols=['SSB'], passband_width_hz=20000, inverting=True,
                uplink_low_hz=None, downlink_low_hz=145900000, downlink_high_hz=145920000)
        band = s.render(self.query('123 field passband'))
        self.assertIn('passband=20000Hz', band)
        self.assertIn('inverting=True', band)
        mode = s.render(self.query('123 field mode'))
        self.assertIn('mode=USB', mode)
        self.assertIn('protocol=SSB', mode)
        self.assertIn('type=Transponder', mode)
        self.assertIn('up=?Hz', s.render(self.query('123 field uplink')))
        self.assertIn('dn=145900000-145920000Hz', s.render(self.query('123 field downlink')))
        self.op('one', 'a', downlink_low_hz=200, downlink_high_hz=100)
        with self.assertRaisesRegex(ValueError, 'Reversed'):
            s.render(self.query('123 field downlink'))

    def test_long_qualifications_are_withheld_not_trimmed(self):
        self.op('one', 'a', schedule='only during ' + 'qualified ' * 30,
                review_required=True, raw={'unconfirmed': True, 'frequency_violation': True})
        result = self.query('123 field downlink')
        self.assertIn('too long', s.render(result))
        self.assertNotIn('Hz', s.render(result))
        self.assertTrue(result['operations'][0]['attributes']['raw']['unconfirmed'])

    def test_service_lookup_discovery_and_unavailable_dependencies(self):
        self.managed()
        root = Path(__file__).resolve().parents[1]
        config = json.loads((root/'config.json').read_bytes())['responder']
        from scripts.command_dependencies import dependency_status
        with patch.dict(os.environ, {'MESHCORE_DATA_DIR': str(self.root), 'MESHCORE_SENDER': 'Alice'}):
            for command, arguments, expected in [('sat', ['name Test'], '123'),
                                                  ('satfreq', ['123 op one field downlink'], '145800000.125Hz')]:
                spec = config['commands']['!'+command]
                direct = subprocess.run([sys.executable, str(root/spec['script']), *arguments],
                                        capture_output=True, text=True, encoding='utf-8', timeout=10)
                self.assertEqual(direct.returncode, 0, direct.stderr)
                self.assertIn(expected, direct.stdout)
                request = dict(sender='Alice', channel_name='Test', channel_id='default', channel_index=3,
                               id='w11', phrase='!'+command+' '+arguments[0], command='!'+command, arguments=arguments)
                output, diagnostic = asyncio.run(responder.run_script(root, spec, request, config))
                self.assertFalse(diagnostic)
                self.assertEqual(output.strip(), direct.stdout.strip())
                parts = responder.reply_parts('Alice', output, max_parts=1)
                self.assertEqual(len(parts), 1)
                self.assertIn(expected, parts[0])
                self.assertLessEqual(len(parts[0].encode()), 150)
                self.assertTrue(dependency_status('!'+command, True).startswith('Partial:'))
            request.update(command='!help', arguments=['satellites'], phrase='!help satellites')
            output, diagnostic = asyncio.run(responder.run_script(root, config['commands']['!help'], request, config))
            self.assertFalse(diagnostic)
            self.assertIn('!sat', output); self.assertIn('!satfreq', output)
            self.registry.write_text(json.dumps({'schema': 1, 'datasets': {'satellites': {'active': None}}}), encoding='utf-8')
            for command in ('sat', 'satfreq'):
                self.assertTrue(dependency_status('!'+command, True).startswith('Unavailable:'))
            output, diagnostic = asyncio.run(responder.run_script(root, config['commands']['!help'], request, config))
            self.assertIn('unavailable', output)

    def test_catalog_without_tracking_or_repository_helpers(self):
        self.managed()
        root = Path(__file__).resolve().parents[1]
        program = """import sys
class BlockImports:
    def find_spec(self, name, *args):
        if name.split('.')[0] in {'skyfield', 'sgp4', 'satellite_database'}:
            raise ImportError('Optional/repository import blocked')
sys.meta_path.insert(0, BlockImports())
from scripts.satellite_lookup import main
main('satfreq', ['123 op one field downlink'])
"""
        env = dict(os.environ, MESHCORE_DATA_DIR=str(self.root), PYTHONIOENCODING='utf-8')
        result = subprocess.run([sys.executable, '-c', program], cwd=root, env=env,
                                capture_output=True, text=True, encoding='utf-8', timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('145800000.125Hz', result.stdout)


    def test_schema_missing_view_and_corrupt_sqlite(self):
        from scripts.command_dependencies import dependency_status
        self.db.execute('DROP VIEW operation_reference'); self.db.commit()
        with self.assertRaisesRegex(ValueError, 'schema'):
            self.query()
        self.assertTrue(dependency_status('!sat', True).startswith('Unavailable:'))
        self.db.close()
        self.dbpath.write_bytes(b'not a SQLite database')
        with self.assertRaises(sqlite3.DatabaseError):
            self.query()

    def test_duplicate_names_are_not_arbitrarily_selected(self):
        self.db.execute("UPDATE satellites SET name='Test' WHERE satellite_id='b'"); self.db.commit()
        self.assertIn('Ambiguous', self.query('name Test')['message'])
        self.assertIn('Not in', self.query('name Tes')['message'])

    def test_source_absence_and_invalid_frequency_values(self):
        self.op('one', 'a', present_in_latest_source=False)
        text = s.render(self.query('123 field downlink'))
        self.assertIn('source absent', text)
        self.assertIn('RF unverified', text)
        for value in ('not-a-frequency', '1e999999999', '1e-999999999', True):
            with self.assertRaises(ValueError):
                s.frequency(value)
        self.assertEqual(s.frequency('145800000.123456789012345678901'), '145800000.123456789012345678901')

    def test_json_output_is_local_only(self):
        output = io.StringIO()
        with redirect_stdout(output), patch.dict(os.environ, {'MESHCORE_REQUEST_ID': 'service'}):
            s.main('satfreq', ['--json', '123'])
        self.assertIn('local-only', output.getvalue())
        self.assertNotIn('145800000', output.getvalue())
        self.assertLessEqual(len(('@Reader ' + output.getvalue().strip()).encode()), 150)


    def test_installed_service_uses_external_satellite_settings(self):
        import service_runner
        settings_dir = self.root / 'installed-config'
        settings_dir.mkdir()
        external = self.root / 'external'
        external.mkdir()
        database = external / 'reference.sqlite3'
        shutil.copyfile(self.dbpath, database)
        with sqlite3.connect(database) as connection:
            connection.execute("UPDATE satellites SET norad_id=789 WHERE satellite_id='a'")
        connection.close()
        settings_file = settings_dir / 'satellite-settings.json'
        settings_file.write_text(json.dumps({'database': '../external/reference.sqlite3'}), encoding='utf-8')
        config_file = settings_dir / 'config.json'
        config_file.write_text('{}', encoding='utf-8')
        with patch.dict(os.environ, {}, clear=False):
            service_runner.load_data_root({}, config_file)
            self.assertEqual(self.query('789')['satellite']['norad_id'], 789)
            settings_file.unlink()
            with self.assertRaises(OSError):
                self.query('123')

    def test_null_registry_entry_cannot_enable_legacy_fallback(self):
        self.managed()
        self.registry.write_text(json.dumps({'schema': 1, 'datasets': {'satellites': None}}), encoding='utf-8')
        with patch.dict(os.environ, {'MESHCORE_DATA_DIR': str(self.root)}):
            with self.assertRaisesRegex(ValueError, 'entry'):
                self.query()

    def test_frequency_precision_survives_json_decode(self):
        text = self.db.execute("SELECT data_json FROM operations WHERE operation_id='one'").fetchone()[0]
        text = text.replace('145800000.125', '145800000.123456789012345678901')
        self.db.execute("UPDATE operations SET data_json=? WHERE operation_id='one'", (text,))
        self.db.commit()
        self.assertIn('145800000.123456789012345678901Hz', s.render(self.query('123 field downlink')))

    def test_unrepresentable_operation_ids_are_not_rewritten(self):
        for identifier in ('bad|id', 'bad id', 'bad\nid'):
            self.op(identifier, 'a')
            with self.assertRaisesRegex(ValueError, 'operation identifier'):
                self.query()
            self.db.execute('DELETE FROM operations WHERE operation_id=?', (identifier,))
            self.db.commit()

    def test_narrow_query_ignores_unrelated_operation_payloads(self):
        self.db.execute("INSERT INTO operations VALUES('aaa','a','Broken','not-json')")
        self.db.commit()
        self.assertIn('145800000.125Hz', s.render(self.query('123 op one field downlink')))

    def test_large_name_ambiguity_remains_explicit(self):
        for number in range(100, 125):
            self.db.execute('INSERT INTO satellites VALUES(?,?,?,?,?)',
                            ('other'+str(number), number+1000, 'Same', 'in orbit', '{}'))
        self.db.commit()
        text = s.render(self.query('name Same'))
        self.assertIn('Ambiguous', text)
        self.assertIn('partial', text)
        self.assertLessEqual(len(('@Reader ' + text).encode()), 150)


    def test_unqualified_failure_and_schedule_are_not_promoted(self):
        self.observation('evidence', 'inactive', datetime.now(timezone.utc).isoformat())
        for state in ('inactive', 'scheduled_off'):
            self.db.execute("UPDATE observations SET status=?, evidence_kind='not_heard'", (state,))
            self.db.commit()
            self.assertEqual(self.query()['operations'][0]['evaluated_status'], 'unknown(unqualified evidence)')

    def test_named_record_without_norad_preserves_source_identity(self):
        self.db.execute("UPDATE satellites SET norad_id=NULL WHERE satellite_id='a'")
        self.db.commit()
        result = self.query('name Test', 'sat')
        self.assertIn('source=a(NORAD unknown)', s.render(result))
        self.assertNotIn('None', s.render(result))

    def test_external_settings_work_through_service_subprocess(self):
        import service_runner
        root = Path(__file__).resolve().parents[1]
        config = json.loads((root / 'config.json').read_bytes())['responder']
        with patch.dict(os.environ, {}, clear=False):
            service_runner.load_data_root({}, self.root / 'config.json')
            request = dict(sender='Alice', channel_name='Test', channel_id='default', channel_index=3,
                           id='w11-external', phrase='!satfreq 123 op one field downlink',
                           command='!satfreq', arguments=['123 op one field downlink'])
            output, diagnostic = asyncio.run(responder.run_script(root, config['commands']['!satfreq'], request, config))
            self.assertFalse(diagnostic)
            self.assertIn('145800000.125Hz', output)
            request.update(command='!help', arguments=['!satfreq'], phrase='!help !satfreq')
            output, diagnostic = asyncio.run(responder.run_script(root, config['commands']['!help'], request, config))
            self.assertFalse(diagnostic)
            self.assertIn('Partial', output)

    def test_new_shared_root_selects_registry_over_old_runtime_alias(self):
        self.managed()
        old_state = self.root / 'old-state'
        old_alias = old_state / 'data/satellites/satellites.sqlite3'
        (self.root / 'satellite-settings.json').write_text(json.dumps({'database': str(old_alias)}), encoding='utf-8')
        (self.root / 'config.json').write_text(json.dumps({'dataset_root': str(self.root)}), encoding='utf-8')
        with patch.dict(os.environ, {'MESHCORE_DATA_DIR': str(self.root), 'MESHCORE_RUNTIME_DIR': str(old_state / 'runtime')}):
            self.assertEqual(self.query()['satellite']['norad_id'], 123)

if __name__ == '__main__':
    unittest.main()

