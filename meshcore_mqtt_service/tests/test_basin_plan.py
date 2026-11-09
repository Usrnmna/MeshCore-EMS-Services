"""W09 source identities, recorded relationships, bounded replies and entry points."""
import asyncio
import csv
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import responder
from scripts import basin_plan_data as d, basin_plan_lookup as q, water_lookup, water_settings
from scripts.command_dependencies import is_bundled


def digest(raw):
    return {'sha256': hashlib.sha256(raw).hexdigest(), 'byte_count': len(raw)}


def csv_bytes(rows, columns):
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=columns)
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode('utf-8')


def member(identifier, name='', **keys):
    return {'object_id_json': json.dumps(identifier), 'wb_name': name, 'gnis_name': '',
            'source_keys_json': json.dumps(keys)}


class Fixture:
    """Publish small checksum-pinned collections with the installed archive/index schemas."""

    def __init__(self, base):
        self.root = base / 'basin_plans'
        self.root.mkdir()
        self.entries = {}
        self.members = {}
        self.names = []
        self.relations = {'beneficial_uses': [], 'calwater_hierarchy': []}
        self.rows = {}
        self.schema = {}
        self.add('svc/0', 'BasinPlanLines', 'regions/01_north_coast',
                 [member('001', 'Clear Creek', wbf_id='007'), member('002', 'Clear Creek', wbf_id=7),
                  member('003', 'Unique Creek', wbf_id=None), member('004', 'No Join', wbf_id=99)])
        self.add('other/0', 'BasinPlanLines', 'regions/02_san_francisco_bay',
                 [member('001', 'Clear Creek', wbf_id='007')])
        self.add('svc/5', 'WB_BenUses', 'regions/01_north_coast', [])
        self.rows['svc/5'] = [
            dict(objectid=1, wbf_id='007', bu_code='AGR', bu_name='Agricultural Supply',
                 bu_desc='Recorded agricultural use.', butype_id='E', bunote_id=0, region_key='1N', region_name='Region 1'),
            dict(objectid=2, wbf_id='007', bu_code='COLD', bu_name='Cold Freshwater Habitat',
                 bu_desc='Recorded habitat use.', butype_id='P', bunote_id='01', region_key='1N', region_name='Region 1'),
            dict(objectid=3, wbf_id=7, bu_code='MUN', bu_name='Municipal Supply',
                 bu_desc='Designation, not measured water quality.', butype_id=None, bunote_id=None, region_key='1N', region_name='Region 1')]
        self.schema['svc/5'] = {'fields': [{'name': 'butype_id', 'domain': {'codedValues': [
            {'code': 'E', 'name': 'Existing'}, {'code': 'P', 'name': 'Potential'}]}}]}
        self.link('beneficial_uses', 'svc/0', 'svc/5', 'wbf_id', 'wbf_id', ['007'], ['007'], 'matched_key_group', 2)
        self.link('beneficial_uses', 'svc/0', 'svc/5', 'wbf_id', 'wbf_id', [7], [7], 'matched_key_group', 1)
        for index, suffix in enumerate(d.LEVELS):
            keys = {d.LEVEL_FIELDS[index]: 'N' if index == 0 else index * 100}
            if index == 1:
                keys['hrc'] = 'N'
            self.add(f'cal/{index}', 'CalWater_Hydrologic_' + suffix,
                     'hydrologic_boundaries/calwater_2_2_1', [member('01', **keys)])
            if index:
                self.link('calwater_hierarchy', f'cal/{index}', f'cal/{index-1}',
                          'hrc' if index == 1 else d.LEVEL_FIELDS[index], d.LEVEL_FIELDS[index-1],
                          ['N' if index == 1 else index * 100], ['N' if index == 1 else (index-1)*100],
                          'verified_code_parent', 1)

    def add(self, key, name, category, members):
        self.entries[key] = dict(key=key, name=name, category=category, object_id_field='objectid',
                                 record_count=len(members), kind='spatial')
        self.members[key] = members
        for row in members:
            if row['wb_name']:
                self.names.append(dict(dataset_key=key, category=category, name=row['wb_name'],
                    name_field='wb_name', name_status='published', matching_records='1',
                    sample_object_ids='[' + row['object_id_json'] + ']'))

    def link(self, family, source, target, left, right, source_key, target_key, status, count):
        self.relations[family].append(dict(relationship_type=family, source_dataset=source,
            target_dataset=target, source_fields=left, target_fields=right,
            source_key_json=d.key_token(source_key), target_key_json=d.key_token(target_key),
            status=status, target_records=str(count)))

    def publish(self):
        source = self.root / 'snapshot'
        review = self.root / 'organized'
        source.mkdir(exist_ok=True)
        review.mkdir(exist_ok=True)
        files = {}
        source_files = {}

        def write(directory, relative, raw, evidence):
            path = directory / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            evidence[relative] = digest(raw)
            return evidence[relative]

        for key, entry in self.entries.items():
            members = self.members[key]
            if key in self.rows:
                rows = self.rows[key]
                entry.update(kind='table', path=key + '/rows.json.gz', metadata_path=key + '/metadata.json',
                             id_evidence_path=key + '/ids.json', record_count=len(rows))
                entry.update(write(source, entry['path'], gzip.compress(json.dumps({'rows': rows}).encode()), source_files))
                write(source, entry['metadata_path'], json.dumps(self.schema[key]).encode(), source_files)
                write(source, entry['id_evidence_path'], json.dumps({'objectIds': [r['objectid'] for r in rows]}).encode(), source_files)
                members = [member(r['objectid'], wbf_id=r.get('wbf_id')) for r in rows]
            else:
                entry['record_count'] = len(members)
            relative = f"{entry['category']}/relationships/record_keys/{hashlib.sha256(key.encode()).hexdigest()[:16]}.csv.gz"
            write(review, relative, gzip.compress(csv_bytes(members, ['object_id_json', 'wb_name', 'gnis_name', 'source_keys_json'])), files)
        write(review, 'names.csv', csv_bytes(self.names, ['dataset_key', 'category', 'name', 'name_field',
              'name_status', 'matching_records', 'sample_object_ids']), files)
        for family, rows in self.relations.items():
            write(review, 'relationships/' + family + '.csv', csv_bytes(rows,
                  ['relationship_type', 'source_dataset', 'target_dataset', 'source_fields', 'target_fields',
                   'source_key_json', 'target_key_json', 'status', 'target_records']), files)
        manifest = dict(schema_version=1, complete=True, snapshot_id='fixture', datasets=list(self.entries.values()), files=source_files,
                        limitations=['Installed reference only; coverage varies.'])
        raw = json.dumps(manifest).encode()
        (source / 'manifest.json').write_bytes(raw)
        pointer = dict(schema_version=1, snapshot_id='fixture', manifest_path='snapshot/manifest.json', manifest_sha256=digest(raw)['sha256'],
                       organization_path='organized')
        report = dict(schema_version=1, snapshot_id='fixture', source_manifest_sha256=pointer['manifest_sha256'],
                      dataset_keys=sorted(self.entries), dataset_count=len(self.entries), files=files)
        raw = json.dumps(report).encode()
        (review / 'organization.json').write_bytes(raw)
        pointer['organization_manifest_sha256'] = digest(raw)['sha256']
        (self.root / 'sources.json').write_text(json.dumps(pointer), encoding='utf-8')


class BasinPlanTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.fixture = Fixture(self.base)
        self.fixture.publish()
        self.config = water_settings.validate({'data_directory': str(self.base)})

    def query(self, text='id BP:svc/0:001', command='waterway'):
        return q.lookup(command, text, self.config)

    def test_exact_source_ids_leading_zeroes_and_collisions(self):
        self.assertEqual(self.query()['id'], 'BP:svc/0:001')
        self.assertEqual(self.query('id BP:other/0:001')['category'], 'regions/02_san_francisco_bay')
        self.assertEqual(self.query('id BP:svc/0:1')['kind'], 'message')
        self.assertEqual(self.query('id BP:missing/0:001')['kind'], 'message')
        self.assertEqual(self.query('id BP:svc/0:001 region 2')['kind'], 'message')
        for text in ('id NHDPlusV2:001', 'id USGS-001', 'id BP:svc/00:001 extra'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.query(text)

    def test_names_require_explicit_region_and_source_without_merging(self):
        result = self.query('name Clear Creek')
        self.assertEqual(len(result['ids']), 3)
        self.assertEqual(self.query('name Clear Creek region 1')['kind'], 'choices')
        self.assertEqual(self.query('name clear creek source other/0 region 2')['id'], 'BP:other/0:001')
        self.assertEqual(self.query('name Unique Creek')['id'], 'BP:svc/0:003')
        self.assertEqual(self.query('name Unknown Creek')['kind'], 'message')
        self.assertEqual(self.query('name Clear Creek region 02_san_francisco_bay')['id'], 'BP:other/0:001')

    def test_parent_names_are_not_waterbody_names_or_connectivity(self):
        self.fixture.names.append(dict(self.fixture.names[0], name='Parent River', name_field='parent_wb'))
        self.fixture.publish()
        self.assertEqual(self.query('name Parent River')['kind'], 'message')
        rendered = q.render(self.query())
        self.assertIn('no connectivity', rendered)
        self.assertNotIn('downstream', rendered)

    def test_name_samples_are_not_complete_membership(self):
        self.fixture.names[0]['matching_records'] = '10'
        self.fixture.publish()
        result = self.query('name Clear Creek source svc/0')
        self.assertEqual(result['kind'], 'choices')
        self.assertTrue(result['partial'])
        self.assertIn('partial', q.render(result))

    def test_six_hierarchy_levels_and_root_are_distinct_from_boards(self):
        for index in range(6):
            with self.subTest(level=index):
                result = self.query(f'parent BP:cal/{index}:01', 'basin')
                self.assertEqual(result['level'], d.LEVEL_NAMES[index])
                self.assertEqual(result['status'], 'verified' if index else 'root')
                if index:
                    self.assertEqual(result['parent'], f'BP:cal/{index-1}:01')
                self.assertIn('not Board regions', q.render(result))
        with self.assertRaises(ValueError):
            self.query('parent BP:svc/0:001', 'basin')

    def test_parent_uses_recorded_key_not_calculated_prefix(self):
        self.fixture.members['cal/0'][0]['source_keys_json'] = json.dumps({'hrc': 'Z'})
        self.fixture.relations['calwater_hierarchy'][0]['target_key_json'] = '["Z"]'
        self.fixture.publish()
        self.assertEqual(self.query('parent BP:cal/1:01', 'basin')['parent'], 'BP:cal/0:01')

    def test_missing_ambiguous_and_conflicting_parents(self):
        self.fixture.relations['calwater_hierarchy'][0]['status'] = 'unmatched_parent_code'
        self.fixture.publish()
        self.assertEqual(self.query('parent BP:cal/1:01', 'basin')['status'], 'unresolved')
        self.fixture.relations['calwater_hierarchy'][0]['status'] = 'verified_code_parent'
        self.fixture.members['cal/0'].append(member('02', hrc='N'))
        self.fixture.publish()
        self.assertIn('ambiguous', q.render(self.query('parent BP:cal/1:01', 'basin')))
        self.fixture.relations['calwater_hierarchy'].clear()
        self.fixture.publish()
        self.assertIn('missing recorded parent', q.render(self.query('parent BP:cal/1:01', 'basin')))

    def test_cycles_and_duplicate_edges_never_choose_a_parent_arbitrarily(self):
        row = self.fixture.relations['calwater_hierarchy'][0]
        self.fixture.relations['calwater_hierarchy'].append(dict(row))
        self.fixture.publish()
        self.assertEqual(self.query('parent BP:cal/1:01', 'basin')['status'], 'verified')
        self.fixture.relations['calwater_hierarchy'].append(dict(row, target_dataset='cal/1'))
        self.fixture.publish()
        self.assertIn('cycle', q.render(self.query('parent BP:cal/1:01', 'basin')))

    def test_published_ancestor_does_not_skip_immediate_level(self):
        self.fixture.link('calwater_hierarchy', 'cal/5', 'cal/1', 'rbuaspw', 'rbu', [500], [100], 'verified_code_parent', 1)
        self.fixture.publish()
        self.assertEqual(self.query('parent BP:cal/5:01', 'basin')['parent'], 'BP:cal/4:01')

    def test_many_to_many_uses_preserve_string_numeric_keys_and_codes(self):
        result = self.query('BP:svc/0:001', 'wateruse')
        self.assertEqual([r['attributes']['bu_code'] for r in result['uses']], ['AGR', 'COLD'])
        self.assertEqual(result['uses'][0]['status'], {'code': 'E', 'description': 'Existing'})
        self.assertEqual(result['uses'][1]['notes'], {'code': '01', 'description': None})
        self.assertEqual(result['uses'][0]['attributes']['bu_desc'], 'Recorded agricultural use.')
        numeric = self.query('BP:svc/0:002', 'wateruse')
        self.assertEqual([r['attributes']['bu_code'] for r in numeric['uses']], ['MUN'])
        self.assertIsNone(numeric['uses'][0]['status']['description'])
        self.assertEqual(d.key_token([7.0]), d.key_token([7]))
        self.assertNotEqual(d.key_token(['007']), d.key_token([7]))

    def test_use_selection_name_resolution_and_missing_classifications(self):
        self.assertEqual(self.query('name Clear Creek', 'wateruse')['kind'], 'choices')
        result = self.query('BP:svc/0:001 use COLD field description', 'wateruse')
        self.assertEqual(len(result['uses']), 1)
        self.assertEqual(result['uses'][0]['attributes']['bu_desc'], 'Recorded habitat use.')
        for text in ('BP:svc/0:003', 'BP:svc/0:004', 'BP:svc/0:001 use UNKNOWN'):
            self.assertTrue(self.query(text, 'wateruse')['qualifications'])
        self.assertIn('no safety/access/conditions', q.render(result).lower())

    def test_cross_service_and_conflicting_joins_are_withheld(self):
        row = self.fixture.relations['beneficial_uses'][0]
        self.fixture.relations['beneficial_uses'].append(dict(row, target_dataset='other/5'))
        self.fixture.publish()
        result = self.query('BP:svc/0:001', 'wateruse')
        self.assertEqual(result['uses'], [])
        self.assertIn('unsupported', result['qualifications'][0])
        self.fixture.relations['beneficial_uses'][-1] = dict(row, status='unmatched_source_key')
        self.fixture.publish()
        self.assertEqual(self.query('BP:svc/0:001', 'wateruse')['uses'], [])

    def test_designation_domains_are_never_inferred(self):
        self.fixture.schema['svc/5'] = {'fields': []}
        self.fixture.publish()
        result = self.query('BP:svc/0:001 use AGR field status', 'wateruse')
        self.assertIsNone(result['uses'][0]['status']['description'])
        self.assertIn('type=E(unresolved)', q.render(result))
        self.assertIn('status=unresolved', q.render(result))

    def test_bounded_results_long_descriptions_and_utf8_radio_limits(self):
        self.fixture.rows['svc/5'][0]['bu_desc'] = 'Sensitive qualification | ' + 'é' * 180
        self.fixture.publish()
        result = self.query('BP:svc/0:001 use AGR field description', 'wateruse')
        self.assertIn('exceed', q.render(result))
        self.assertIn('Sensitive qualification | ', result['uses'][0]['attributes']['bu_desc'])
        cases = [result, self.query(), self.query('name Clear Creek'), self.query('parent BP:cal/5:01', 'basin'),
                 self.query('BP:svc/0:001', 'wateruse'), {'kind': 'help', 'text': q.HELP['wateruse']}]
        for sender in ('Reader', 'é' * 40):
            with patch.dict(os.environ, {'MESHCORE_SENDER': sender}):
                for value in cases:
                    output = q.render(value)
                    self.assertNotIn(' | ', output)
                    replies = responder.reply_parts(sender, output, max_parts=1)
                    self.assertEqual(len(replies), 1)
                    self.assertLessEqual(len(replies[0].encode('utf-8')), 150)
                    self.assertEqual(replies[0], '@' + sender + ' ' + output)

    def test_integrity_failure_and_incompatible_generation(self):
        path = self.fixture.root / 'organized/names.csv'
        path.write_bytes(path.read_bytes() + b'bad')
        with self.assertRaisesRegex(ValueError, 'integrity'):
            self.query('name Clear Creek')
        self.fixture.publish()
        path = self.fixture.root / 'organized/organization.json'
        report = json.loads(path.read_bytes())
        report['snapshot_id'] = 'other'
        raw = json.dumps(report).encode()
        path.write_bytes(raw)
        pointer_path = self.fixture.root / 'sources.json'
        pointer = json.loads(pointer_path.read_bytes())
        pointer['organization_manifest_sha256'] = digest(raw)['sha256']
        pointer_path.write_text(json.dumps(pointer), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Incompatible'):
            self.query()

    def test_designation_membership_count_mismatch_fails(self):
        self.fixture.relations['beneficial_uses'][0]['target_records'] = '3'
        self.fixture.publish()
        with self.assertRaisesRegex(ValueError, 'membership conflict'):
            self.query('BP:svc/0:001', 'wateruse')

    def test_missing_source_and_designation_file_integrity(self):
        path = self.fixture.root / 'snapshot/svc/5/rows.json.gz'
        path.write_bytes(path.read_bytes() + b'damaged')
        with self.assertRaisesRegex(ValueError, 'integrity'):
            self.query('BP:svc/0:001', 'wateruse')
        path.unlink()
        with self.assertRaises(FileNotFoundError):
            self.query('BP:svc/0:001', 'wateruse')
        other = water_settings.validate({'data_directory': str(self.base / 'absent')})
        with self.assertRaises(FileNotFoundError):
            q.lookup('waterway', 'id BP:svc/0:001', other)

    def test_duplicate_object_identity_and_conflicting_parent_targets(self):
        self.fixture.members['svc/0'].append(member('001', 'Other record', wbf_id=42))
        self.fixture.publish()
        with self.assertRaisesRegex(ValueError, 'Ambiguous source object'):
            self.query()
        self.fixture.members['cal/0'].append(member('02', hrc='Z'))
        row = self.fixture.relations['calwater_hierarchy'][0]
        self.fixture.relations['calwater_hierarchy'].append(dict(row, target_key_json='["Z"]'))
        self.fixture.publish()
        result = self.query('parent BP:cal/1:01', 'basin')
        self.assertEqual(result['status'], 'unresolved')
        self.assertIn('conflicting parents', result['qualifications'])

    def test_use_qualifications_cannot_be_silently_removed_to_fit(self):
        self.fixture.rows['svc/5'][0]['qualification'] = 'Recorded seasonal limitation | ' + 'restricted ' * 20
        self.fixture.publish()
        result = self.query('BP:svc/0:001 use AGR', 'wateruse')
        output = q.render(result)
        self.assertIn('exceed', output)
        self.assertNotIn('AGR', output)
        self.assertIn('Recorded seasonal limitation', result['uses'][0]['attributes']['qualification'])

    def test_name_limit_and_use_limit_disclose_incomplete_results(self):
        with patch.object(q, 'MAX_MATCHES', 1):
            result = self.query('name Clear Creek')
            self.assertTrue(result['partial'])
            self.assertEqual(result['kind'], 'choices')
            with self.assertRaisesRegex(ValueError, 'select use CODE'):
                self.query('BP:svc/0:001', 'wateruse')

    def test_disabled_feature_remains_disabled(self):
        config = dict(self.config, enabled=False)
        self.assertIn('disabled', q.lookup('wateruse', 'BP:svc/0:001', config)['text'])

    def test_named_use_result_keeps_followup_identity_and_unresolved_status(self):
        # Use full-length source identity to exercise the real radio budget.
        key = 'a' * 32 + '/0'
        self.fixture.add(key, 'BasinPlanLines', 'regions/01_north_coast',
                         [member('001', 'Named River', wbf_id='007')])
        self.fixture.publish()
        result = self.query('name Named River', 'wateruse')
        self.assertTrue(result['qualifications'])
        for sender in ('Reader', 'é' * 40):
            with patch.dict(os.environ, {'MESHCORE_SENDER': sender}):
                output = q.render(result)
                self.assertIn('BP:' + key + ':001', output)
                self.assertIn('unresolved', output)
                self.assertLessEqual(len(('@' + sender + ' ' + output).encode()), 150)
        # Successful named results also retain identity when descriptions cannot fit.
        result['qualifications'] = []
        result['uses'] = self.query('BP:svc/0:001', 'wateruse')['uses']
        with patch.dict(os.environ, {'MESHCORE_SENDER': 'é' * 40}):
            self.assertEqual(q.render(result), 'Use !wateruse ' + result['id'])

    def test_dataset_wide_relationship_failure_cannot_hide_behind_valid_join(self):
        for family, command, text in [('beneficial_uses', 'wateruse', 'BP:svc/0:001'),
                                       ('calwater_hierarchy', 'basin', 'parent BP:cal/1:01')]:
            with self.subTest(family=family):
                row = self.fixture.relations[family][0]
                self.fixture.relations[family].append(dict(row, source_key_json='', target_key_json='',
                                                           status='missing_target_fields'))
                self.fixture.publish()
                result = self.query(text, command)
                self.assertIn('missing_target_fields', result['qualifications'])
                if command == 'wateruse':
                    self.assertEqual(result['uses'], [])
                else:
                    self.assertEqual(result['status'], 'unresolved')

    def test_schema_versions_and_incomplete_markers_are_rejected(self):
        for target in ('sources.json', 'snapshot/manifest.json', 'organized/organization.json'):
            for value in (2, None, True):
                with self.subTest(target=target, value=value):
                    self.fixture.publish()
                    path = self.fixture.root / target
                    document = json.loads(path.read_bytes())
                    document['schema_version'] = value
                    path.write_text(json.dumps(document), encoding='utf-8')
                    self.repin()
                    with self.assertRaisesRegex(ValueError, 'schema version'):
                        self.query()
        for complete in ('false', 1, False):
            with self.subTest(complete=complete):
                self.fixture.publish()
                path = self.fixture.root / 'snapshot/manifest.json'
                document = json.loads(path.read_bytes())
                document['complete'] = complete
                path.write_text(json.dumps(document), encoding='utf-8')
                self.repin()
                with self.assertRaisesRegex(ValueError, 'Incompatible'):
                    self.query()

    def repin(self):
        """Update hashes after deliberate, structurally valid fixture mutations."""
        root = self.fixture.root
        pointer = json.loads((root / 'sources.json').read_bytes())
        pointer['manifest_sha256'] = digest((root / 'snapshot/manifest.json').read_bytes())['sha256']
        path = root / 'organized/organization.json'
        report = json.loads(path.read_bytes())
        report['source_manifest_sha256'] = pointer['manifest_sha256']
        path.write_text(json.dumps(report), encoding='utf-8')
        pointer['organization_manifest_sha256'] = digest(path.read_bytes())['sha256']
        (root / 'sources.json').write_text(json.dumps(pointer), encoding='utf-8')

    def test_unavailable_reply_reaches_service_without_generic_replacement(self):
        root = Path(__file__).resolve().parents[1]
        config = json.loads((root / 'config.json').read_bytes())['responder']
        config['water'] = self.config
        path = self.fixture.root / 'snapshot/svc/5/rows.json.gz'
        path.write_bytes(path.read_bytes() + b'damaged')
        request = dict(sender='Alice', channel_name='Test', channel_id='default', channel_index=3,
                       id='w09', phrase='!wateruse BP:svc/0:001', command='!wateruse', arguments=['BP:svc/0:001'])
        output, diagnostic = asyncio.run(responder.run_script(root, config['commands']['!wateruse'], request, config))
        self.assertFalse(diagnostic)
        self.assertIn('integrity failure', output)

    def test_explicit_removal_and_generation_swap(self):
        (self.base / 'datasets.json').write_text(json.dumps({'schema': 1, 'datasets': {'basin_plans': {'active': None}}}), encoding='utf-8')
        with patch.dict(os.environ, {'MESHCORE_DATA_DIR': str(self.base)}):
            with self.assertRaises(FileNotFoundError):
                self.query()
        (self.base / 'datasets.json').unlink()
        with self.assertRaisesRegex(ValueError, 'changed'):
            with d.Collection(self.config):
                pointer = self.fixture.root / 'sources.json'
                pointer.write_bytes(pointer.read_bytes() + b' ')

    def test_file_change_after_read_fails_before_result(self):
        with self.assertRaisesRegex(ValueError, 'changed'):
            with d.Collection(self.config) as collection:
                list(collection.csv_rows('names.csv'))
                path = self.fixture.root / 'organized/names.csv'
                path.write_bytes(path.read_bytes() + b' ')

    def test_query_limits_and_malformed_selectors(self):
        for text in ('name', 'id BP:svc/0:001 region 1 region 2', 'name Clear Creek source', 'id BP:svc/0:001\n', 'é' * 76):
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.query(text)
        for text in ('BP:svc/0:001 field status', 'BP:svc/0:001 use AGR field bogus'):
            with self.assertRaises(ValueError):
                self.query(text, 'wateruse')
        with patch.object(d, 'QUERY_SECONDS', -1), self.assertRaisesRegex(ValueError, 'limit'):
            self.query()
        with patch.object(d, 'MAX_ROWS', 1), self.assertRaisesRegex(ValueError, 'limit'):
            self.query()

    def test_location_parsers_and_service_dispatch_preserved(self):
        for command in ('waterway', 'basin'):
            self.assertEqual(water_lookup.parse_query(command, '37.8 -122.2')['action'], 'lookup')
            self.assertEqual(water_lookup.parse_query(command, 'Oakland CA')['action'], 'lookup')
        config = json.loads((Path(__file__).resolve().parents[1] / 'config.json').read_bytes())['responder']
        for command, text in [('waterway', 'name Clear Creek'), ('basin', 'parent BP:cal/5:01'), ('wateruse', 'BP:svc/0:001')]:
            matched = responder.match_command('!' + command + ' ' + text, config['commands'])
            self.assertEqual(matched, ('!' + command, [text], None))
            self.assertTrue(is_bundled('!' + command, config['commands']['!' + command]))

    def test_direct_custom_paths_structured_and_service_invocation(self):
        root = Path(__file__).resolve().parents[1]
        config = json.loads((root / 'config.json').read_bytes())['responder']
        config['water'] = self.config
        env = dict(os.environ, MESHCORE_WATER_SETTINGS=json.dumps(self.config), PYTHONIOENCODING='utf-8')
        for command, text in [('waterway', 'id BP:svc/0:001'), ('basin', 'parent BP:cal/5:01'), ('wateruse', 'BP:svc/0:001 use AGR')]:
            spec = config['commands']['!' + command]
            self.assertEqual(spec['script'], 'scripts/' + command + '.py')
            self.assertEqual(spec['args'], [])
            direct = subprocess.run([sys.executable, str(root / spec['script']), text], cwd=self.base,
                                    env=env, text=True, capture_output=True, timeout=15)
            self.assertEqual(direct.returncode, 0, direct.stderr)
            request = dict(sender='Alice', channel_name='Test', channel_id='default', channel_index=3,
                           id='w09', phrase='!' + command + ' ' + text, command='!' + command, arguments=[text])
            output, diagnostic = asyncio.run(responder.run_script(root, spec, request, config))
            self.assertFalse(diagnostic)
            self.assertEqual(output.strip(), direct.stdout.strip())
            structured = subprocess.run([sys.executable, str(root / spec['script']), '--json', text], cwd=self.base,
                                        env=env, text=True, capture_output=True, timeout=15)
            self.assertEqual(structured.returncode, 0, structured.stderr)
            self.assertIn('snapshot', json.loads(structured.stdout))


if __name__ == '__main__':
    unittest.main()
