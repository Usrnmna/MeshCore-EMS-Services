"""Reviewed one-hop connectivity, generation integrity and command contracts."""
import asyncio
from contextlib import contextmanager
import hashlib
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
from scripts import connectivity_lookup as c, water_settings


def database(path=':memory:'):
    """Create the source tables needed by one-hop queries without geometry inference."""
    db=sqlite3.connect(path);db.row_factory=sqlite3.Row
    db.executescript('''CREATE TABLE reaches(reach_id TEXT PRIMARY KEY,name TEXT,enabled INTEGER,flow_direction TEXT,terminal INTEGER,tidal INTEGER,divergence INTEGER,feature_type TEXT);
    CREATE TABLE flow_connections(from_reach_id TEXT,to_reach_id TEXT,status TEXT,evidence_class TEXT);
    CREATE TABLE tributary_connections(upstream_reach_id TEXT,downstream_reach_id TEXT,relationship TEXT,evidence_class TEXT);
    CREATE TABLE station_routing_coverage(station_id TEXT,source_reach_id TEXT,status TEXT);
    CREATE TABLE reach_regions(reach_id TEXT,region TEXT);''')
    for rid,name in [('001','Creek'),('002','River'),('003','Creek')]:
        db.execute('INSERT INTO reaches VALUES(?,?,1,?,0,0,0,?)',(rid,name,'With Digitized','StreamRiver'))
    db.executemany('INSERT INTO reach_regions VALUES(?,?)',[('001','north'),('003','south')])
    db.execute('INSERT INTO station_routing_coverage VALUES(?,?,?)',('USGS-0001','001','paths_to_source_terminals'))
    db.execute('INSERT INTO station_routing_coverage VALUES(?,?,?)',('OTHER-0001','003','missing_published_station_reach'))
    return db


def edge(db,a,b,status='published_node_connection',evidence='published_node_key_join'):
    db.execute('INSERT INTO flow_connections VALUES(?,?,?,?)',(a,b,status,evidence))


class ConnectivityTests(unittest.TestCase):
    def setUp(self):
        self.db=database();self.addCleanup(self.db.close)
        self.config=water_settings.validate({})
        @contextmanager
        def source(config):
            yield self.db
        p=patch.object(c,'routing',source);p.start();self.addCleanup(p.stop)

    def query(self,text,command='downstream'):
        return c.lookup(command,text,self.config)

    def test_exact_ids_and_agency_collisions(self):
        edge(self.db,'001','002')
        self.assertIn('NHDPlusV2:002',self.query('USGS-0001'))
        self.assertIn('withheld',self.query('OTHER-0001'))
        self.assertIn('withheld',self.query('USGS-1'))
        self.assertIn('not found',self.query('NHDPlusV2:1'))
        with self.assertRaises(ValueError):self.query('OtherNetwork:001')

    def test_unsupported_or_conflicting_station_link_is_withheld(self):
        self.db.execute("UPDATE station_routing_coverage SET status='published_reachcode_mismatch_requires_review'")
        self.assertIn('withheld',self.query('USGS-0001'))
        self.db.execute("INSERT INTO station_routing_coverage VALUES('USGS-0001','003','paths_to_source_terminals')")
        self.assertIn('withheld',self.query('USGS-0001'))

    def test_branches_and_qualifications(self):
        edge(self.db,'001','002');edge(self.db,'001','003')
        self.db.execute("UPDATE reaches SET tidal=1,divergence=2 WHERE reach_id='003'")
        result=self.query('NHDPlusV2:001')
        for word in ('branches','tidal','divergence','NHDPlusV2:002','NHDPlusV2:003'):self.assertIn(word,result)

    def test_cycles_and_duplicates_are_bounded_to_one_hop(self):
        edge(self.db,'001','002');edge(self.db,'002','001');edge(self.db,'001','002');edge(self.db,'001','001')
        result=self.query('NHDPlusV2:001')
        self.assertIn('one hop',result);self.assertIn('duplicate edges',result);self.assertIn('self-cycle',result)
        self.assertEqual(result.count('NHDPlusV2:002'),1)

    def test_conflicting_duplicate_edges_are_not_supported_connections(self):
        edge(self.db,'001','002')
        edge(self.db,'001','002','direction_or_enabled_requires_review')
        result=self.query('NHDPlusV2:001')
        self.assertIn('conflicting edges',result)
        self.assertNotIn('NHDPlusV2:002',result)

    def test_tributary_cannot_flow_out_of_a_declared_terminal(self):
        edge(self.db,'001','002')
        self.db.execute("UPDATE reaches SET terminal=1 WHERE reach_id='001'")
        self.db.execute("INSERT INTO tributary_connections VALUES('001','002','confluence_incoming_branch','published_node_key_join')")
        result=self.query('NHDPlusV2:002','tributaries')
        self.assertIn('terminal/edge conflict',result)
        self.assertNotIn('NHDPlusV2:001',result)

    def test_missing_divergence_is_not_silently_unqualified(self):
        edge(self.db,'001','002')
        self.db.execute("UPDATE reaches SET divergence=NULL WHERE reach_id='002'")
        self.assertIn('divergence unknown',self.query('NHDPlusV2:001'))

    def test_terminal_is_distinct_from_missing_or_excluded_edges(self):
        self.assertIn('unresolved',self.query('NHDPlusV2:001'))
        edge(self.db,'001','','source_terminal')
        self.assertNotIn('Verified source terminal',self.query('NHDPlusV2:001'))
        self.db.execute("UPDATE reaches SET terminal=1 WHERE reach_id='001'")
        self.assertIn('Verified source terminal',self.query('NHDPlusV2:001'))
        edge(self.db,'001','002')
        self.assertIn('conflict',self.query('NHDPlusV2:001'))

    def test_terminal_requires_supported_evidence_and_consistent_edges(self):
        self.db.execute("UPDATE reaches SET terminal=1 WHERE reach_id='001'")
        edge(self.db,'001','','source_terminal','unreviewed')
        self.assertNotIn('Verified source terminal',self.query('NHDPlusV2:001'))
        self.db.execute('DELETE FROM flow_connections')
        edge(self.db,'001','002')
        self.assertIn('conflict',self.query('NHDPlusV2:001'))

    def test_direction_coastline_and_missing_destinations(self):
        edge(self.db,'001','missing');edge(self.db,'001','002','direction_or_enabled_requires_review')
        result=self.query('NHDPlusV2:001');self.assertIn('unresolved',result);self.assertNotIn('NHDPlusV2:002',result)
        self.db.execute("UPDATE reaches SET feature_type='Coastline' WHERE reach_id='001'")
        self.assertIn('coastline excluded',self.query('NHDPlusV2:001'))

    def test_named_waterbody_region_and_source_selection(self):
        result=self.query('name Creek','tributaries');self.assertIn('Choose exact',result)
        self.assertIn('NHDPlusV2:001',result);self.assertIn('NHDPlusV2:003',result)
        self.assertNotIn('Choose exact',self.query('name Creek region north','tributaries'))
        self.assertIn('No exact',self.query('name Cree','tributaries'))

    def test_tributaries_require_confluence_and_supported_directed_edge(self):
        self.db.execute("INSERT INTO tributary_connections VALUES('001','002','confluence_incoming_branch','published_node_key_join')")
        self.assertNotIn('NHDPlusV2:001',self.query('NHDPlusV2:002','tributaries'))
        edge(self.db,'001','002')
        self.assertIn('NHDPlusV2:001',self.query('NHDPlusV2:002','tributaries'))
        self.assertNotIn('NHDPlusV2:002',self.query('NHDPlusV2:001','tributaries'))

    def test_confluence_conflicts_and_cutoff_do_not_select_an_edge(self):
        edge(self.db,'001','002')
        self.db.executemany('INSERT INTO tributary_connections VALUES(?,?,?,?)',[
            ('001','002','confluence_incoming_branch','published_node_key_join'),
            ('001','002','unreviewed','published_node_key_join')])
        with patch.object(c,'MAX_ROWS',1):
            result=self.query('NHDPlusV2:002','tributaries')
        self.assertIn('conflicting confluence',result)
        self.assertNotIn('NHDPlusV2:001',result)

    def test_excluded_incoming_and_downstream_links_retain_qualification(self):
        edge(self.db,'001','002','coastline_connection_not_river_routing')
        self.assertIn('coastline excluded',self.query('NHDPlusV2:001'))
        self.assertIn('excluded incoming links',self.query('NHDPlusV2:002','tributaries'))

    def test_limits_disclose_partial_and_preserve_qualifications(self):
        for i in range(30):
            rid=str(100+i);self.db.execute('INSERT INTO reaches VALUES(?,?,1,?,0,1,0,?)',(rid,'Branch','With Digitized','StreamRiver'));edge(self.db,'001',rid)
        for sender in ('Alice','a'*80):
            with patch.dict(os.environ,{'MESHCORE_SENDER':sender}):
                result=self.query('NHDPlusV2:001')
                self.assertLessEqual(len(('@'+sender+' '+result).encode()),150)
                self.assertIn('partial',result)
                if 'NHDPlusV2:' in result:self.assertIn('tidal',result)

    def test_malformed_queries(self):
        for command,text in [('downstream','USGS-1 extra'),('downstream','NHDPlusV2:1\n'),('tributaries','name'),('tributaries','name Creek region north extra'),('downstream','x'*151)]:
            with self.subTest(text=text),self.assertRaises(ValueError):c.parse(command,text)


class GenerationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.root=self.base/'usgs_water';self.root.mkdir()
        self.config=water_settings.validate({'data_directory':str(self.base)})
        (self.base/'basin_plans').mkdir();(self.base/'basin_plans/sources.json').write_text('{}')
        inventory=self.publish('inventory',{})
        network=self.publish('network',{'inventory_pointer':inventory})
        review=self.publish('link_review',{'inventory_pointer':inventory,'network_pointer':network})
        folder=self.root/'routing';folder.mkdir()
        db=database(folder/'routing.sqlite');edge(db,'001','002');db.commit();db.close()
        raw=(folder/'routing.sqlite').read_bytes()
        self.publish('routing',{'network':c.NETWORK,'inventory_pointer':inventory,'network_pointer':network,
            'link_review_pointer':review,'basin_pointer':{},'files':{'routing.sqlite':{'byte_count':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}}})

    def publish(self,kind,fields):
        folder=self.root/kind;folder.mkdir(exist_ok=True)
        raw=json.dumps(dict(kind=kind,complete=True,**fields)).encode();(folder/'manifest.json').write_bytes(raw)
        pointer={'manifest_path':kind+'/manifest.json','byte_count':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
        (self.root/(kind+'.json')).write_text(json.dumps(pointer));return pointer

    def test_custom_path_cli_and_service_registration(self):
        self.assertIn('NHDPlusV2:002',c.lookup('downstream','USGS-0001',self.config))
        root=Path(__file__).resolve().parents[1]
        config=json.loads((root/'config.json').read_bytes())['responder'];config['water']=self.config
        for command,text in [('downstream','USGS-0001'),('tributaries','name Creek region north')]:
            spec=config['commands']['!'+command];self.assertEqual(spec['script'],'scripts/'+command+'.py');self.assertEqual(spec['args'],[])
            env=dict(os.environ,MESHCORE_WATER_SETTINGS=json.dumps(self.config),PYTHONIOENCODING='utf-8')
            result=subprocess.run([sys.executable,str(root/spec['script']),text],env=env,cwd=self.base,capture_output=True,text=True,timeout=15)
            self.assertEqual(result.returncode,0,result.stderr)
            request=dict(sender='Alice',channel_name='Test',channel_id='default',channel_index=3,id='w08',phrase='!'+command+' '+text,command='!'+command,arguments=[text])
            output,diagnostic=asyncio.run(responder.run_script(root,spec,request,config))
            self.assertFalse(diagnostic);self.assertEqual(output.strip(),result.stdout.strip())

    def test_checksum_and_generation_mismatch_fail(self):
        with (self.root/'routing/routing.sqlite').open('ab') as stream:stream.write(b'damaged')
        with self.assertRaises(ValueError):c.lookup('downstream','USGS-0001',self.config)

    def test_dependency_and_mid_query_changes_fail(self):
        with self.assertRaises(ValueError):
            with c.routing(self.config):
                (self.root/'inventory.json').write_text('{}')
        with self.assertRaises((ValueError,KeyError)):
            c.lookup('downstream','USGS-0001',self.config)

    def test_sql_budget_is_enforced(self):
        with patch.object(c,'SQL_SECONDS',-1),self.assertRaises(sqlite3.OperationalError):
            with c.routing(self.config) as db:
                db.execute('WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM n WHERE x<1000000) SELECT sum(x) FROM n').fetchone()

    def test_valid_but_changed_dependency_generations_are_rejected(self):
        for kind in ('inventory','network','link_review'):
            with self.subTest(kind=kind):
                manifest_path=self.root/kind/'manifest.json'
                pointer_path=self.root/(kind+'.json')
                original_manifest=manifest_path.read_bytes()
                original_pointer=pointer_path.read_bytes()
                fields=json.loads(original_manifest)
                fields.pop('kind');fields.pop('complete')
                self.publish(kind,dict(fields,revision='new'))
                with self.assertRaisesRegex(ValueError,'Incompatible'):
                    c.lookup('downstream','USGS-0001',self.config)
                manifest_path.write_bytes(original_manifest)
                pointer_path.write_bytes(original_pointer)

    def test_routing_bytes_changed_during_query_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'changed'):
            with c.routing(self.config):
                with (self.root/'routing/routing.sqlite').open('ab') as stream:
                    stream.write(b'changed')

    def test_managed_removal_never_falls_back_to_checkout(self):
        (self.base/'datasets.json').write_text(json.dumps({'schema':1,'datasets':{'usgs_water':{'active':None}}}))
        with patch.dict(os.environ,{'MESHCORE_DATA_DIR':str(self.base)}),self.assertRaises(FileNotFoundError):
            c.lookup('downstream','USGS-0001',water_settings.validate({}))

if __name__=='__main__':unittest.main()
