"""Single-message response contracts, with deterministic provider fixtures."""
import json
import os
import re
from datetime import timedelta
from pathlib import Path
import unittest
from unittest.mock import patch

import responder
from scripts import response_text, water_lookup, landslide_lookup, lightning
from scripts import water_notifications, wildfire_lookup, fire_environment
from scripts import nearby_river_stations, highway_info
from test_floodwarn_responses import snapshot, record
from test_landslide import snapshot as slide_snapshot, feature
from test_lightning import NOW, POINT, alerts, grid, row, weather


class DeliveryFormattingTests(unittest.TestCase):
    def test_single_reply_preserves_warning_for_long_sender(self):
        data = snapshot(record("Flash Flood Warning"))
        for sender in ("Alice", "a" * 80, "温" * 26):
            with patch.dict(os.environ, {"MESHCORE_SENDER": sender}):
                result = water_lookup.format_floodwarn(data)
                parts = responder.reply_parts(sender, result, max_parts=1)
                self.assertEqual(len(parts), 1)
                self.assertLessEqual(len(parts[0].encode()), 150)
                self.assertIn("FLASH FLOOD WARNING", parts[0])
                self.assertIn("Move to higher ground now", parts[0])
                self.assertNotIn("Next:", parts[0])

    def test_removed_routes_rejected_before_execution(self):
        config = json.loads((Path(__file__).resolve().parents[1] / "config.json").read_text())['responder']
        self.assertEqual(config['max_reply_parts'], 1)
        for command, spec in config['commands'].items():
            self.assertEqual(spec.get('max_reply_parts', 1), 1)
            for suffix in ("details Sacramento", "Sacramento page 2"):
                result = responder.match_command(command + " " + suffix, config['commands'])
                if result is not None:
                    self.assertIsNotNone(result[2])

    def test_whole_optional_fields_survive_rebudgeting_without_notices(self):
        url = "https://api.weather.gov/alerts/example-warning"
        value = response_text.compact_fields("Status unknown.", [url, "x" * 200])
        self.assertIn(url, value)
        self.assertNotIn("omitted", value)
        result = responder.reply_parts("a" * 80, value, max_parts=1)[0]
        self.assertLessEqual(len(result.encode()), 150)
        self.assertIn("Status unknown.", result)
        self.assertNotIn("omitted", result)
        self.assertIn(url, result)

    def test_location_named_page_is_not_a_paging_request(self):
        self.assertEqual(water_lookup.parse_query('floodwarn', 'Page AZ')['target'], 'Page AZ')
        self.assertEqual(wildfire_lookup.parse_query('firezone', 'Page AZ')['target'], 'Page AZ')

    def test_high_priority_reports_remain_meaningful_with_long_tag(self):
        sender = 'a' * 80
        with patch.dict(os.environ, {'MESHCORE_SENDER': sender}):
            fire = wildfire_lookup.format_report({
                'query': {'command': 'firewarn'}, 'sources': [{'stale': True}],
                'alerts': [{'properties': {'event': event, 'expires': None}}
                           for event in ('Fire Weather Watch', 'Red Flag Warning')],
            })
            danger = fire_environment.format_report({
                'command': 'firedanger', 'station': None,
                'alerts': [{'properties': {'event': 'Red Flag Warning'}}],
            })
            river = nearby_river_stations.format_mesh_report([
                dict(station_id='ABC', station_name='River', distance_miles=1,
                     river_stage_feet=25, minor_flood_stage_feet=20, action_stage_feet=10)
            ], 15)
            traffic = highway_info.format_radio_report(80, 'Closed to all traffic. Chain controls in effect.')
            cases = [(fire, ('Red Flag Warning', 'Data limited')),
                     (danger, ('Red Flag Warning', 'ERC excludes wind')),
                     (river, ('flood threshold', 'point flooding unknown')),
                     (traffic, ('closures reported', 'Chain controls'))]
            for output, required in cases:
                with self.subTest(output=output):
                    parts = responder.reply_parts(sender, output, max_parts=1)
                    self.assertEqual(len(parts), 1)
                    self.assertLessEqual(len(parts[0].encode()), 150)
                    for phrase in required:
                        self.assertIn(phrase, parts[0])
                    self.assertNotIn('omitted', parts[0])
                    self.assertNotIn('Unable to return', parts[0])

    def test_flash_notification_preserves_action_and_unknown_priority(self):
        alert = record('Flash Flood Warning', urgency='Unknown')
        notice = water_notifications.active_notice(alert, 'ACTIVE')
        output = water_notifications.format_notification(notice, 'Sacramento', NOW.timestamp())
        result = responder.reply_parts('a' * 80, output, max_parts=1)[0]
        self.assertIn('Move to higher ground now', result)
        self.assertIn('Priority unknown', result)
        self.assertLessEqual(len(result.encode()), 150)

    def test_single_message_has_no_counter_and_oversized_core_is_explicit(self):
        self.assertEqual(responder.reply_parts("Alice", "No active alerts.", max_parts=1), ["@Alice No active alerts."])
        parts = responder.reply_parts("a" * 80, "Unknown status. " * 100, max_parts=1)
        self.assertEqual(len(parts), 1)
        self.assertIn("Unable to return", parts[0])
        self.assertLessEqual(len(parts[0].encode()), 150)

    def test_optional_splitter_remains_word_and_utf8_safe(self):
        parts = response_text.tagged_parts("Alice", "Café observations unknown. " * 20, max_parts=4)
        self.assertTrue(all(len(p.encode()) <= 150 for p in parts))
        self.assertTrue(all(p.startswith(f"@Alice [{i}/4] ") for i, p in enumerate(parts, 1)))
        self.assertNotIn("omitted", parts[-1])

    def test_flood_unknown_never_becomes_clear(self):
        data = snapshot(record())
        data['official']['status'] = 'unavailable'
        result = water_lookup.format_floodwarn(data)
        self.assertIn('status unknown', result)
        self.assertNotIn('No active', result)

    def test_landslide_qualified_mentions_remain_qualified(self):
        data = slide_snapshot(records=[feature(description="Debris flows are not expected.", headline="Weather statement", instruction="Watch for mudslides.")])
        result = landslide_lookup.format_alerts(data, "Pasadena", {"max_alerts": 3})
        self.assertIn("qualified mention only", result)
        self.assertIn("Debris flows are not expected.", data['alerts']['a']['properties']['description'])
        self.assertIn("not an all-clear", landslide_lookup.format_alerts(slide_snapshot(records=[]), "Pasadena", {}))

    def test_lightning_chance_is_not_an_official_warning(self):
        with patch.object(lightning, "get_json", side_effect=[POINT, alerts(), grid(row([weather("slight_chance", "thunderstorms")]))]):
            result = lightning.lookup("38 -121", NOW)
        self.assertIn("slight chance thunderstorms", result)
        self.assertNotIn("Lightning Strike Warning", result)

    def test_traffic_removes_generic_repetition_but_keeps_qualified_controls(self):
        for separator, sender in ((separator, sender) for separator in ('\n\n', ' ')
                                  for sender in ('Alice', 'a' * 80)):
            report = 'Closed at Example Pass.' + separator + 'Chain controls in effect.'
            with self.subTest(separator=separator, sender=sender), patch.dict(os.environ, {'MESHCORE_SENDER': sender}):
                text = highway_info.format_radio_report(80, report)
                self.assertEqual(text.lower().count('chain controls'), 1)
                self.assertIn('closures reported', text)
                self.assertIn('Chain controls.', text)
                self.assertLessEqual(len(('@' + sender + ' ' + text).encode()), 150)
        text = highway_info.format_radio_report(80, 'Chains required from A to B except 4WD with snow tires.')
        self.assertIn('except 4WD with snow tires', text)
        self.assertIn('from A to B', text)

    def test_river_counts_and_uncertainty_appear_once(self):
        station = dict(station_id='ABC', station_name='Example River', distance_miles=1,
                       river_stage_feet=21, minor_flood_stage_feet=20, action_stage_feet=15)
        for count, label in ((1, '1 station'), (2, '2 stations')):
            text = nearby_river_stations.format_mesh_report([station] * count, 15)
            self.assertIn(label + ' |', text)
            self.assertNotIn('1 stations', text)
            self.assertEqual(text.count('flooding'), 1)
            self.assertIn('point flooding unknown', text)
            self.assertIn('flood threshold', text)

    def test_lightning_window_counts(self):
        for count, label in ((1, '1 hazard window'), (2, '2 hazard windows')):
            periods = [row([weather('slight_chance', 'thunderstorms')], NOW + timedelta(hours=2*i), 'PT1H')
                       for i in range(count)]
            with patch.object(lightning, 'get_json', side_effect=[POINT, alerts(), grid(row([]), *periods)]):
                text = lightning.lookup('38 -121', NOW)
            self.assertIn(label + ' |', text)
            self.assertNotIn('1 hazard windows', text)

    def test_incident_and_context_record_counts(self):
        incident = dict(name='Example Fire', containment=35, acres=120, display_id='EXAMPLE-1')
        for count, noun in ((0, 'records'), (1, 'record'), (2, 'records')):
            data = dict(query=dict(command='firedata', category='aqi'), sources=[],
                        features=[dict(properties=dict(SiteName='Monitor', PM25_AQI=75))] * count)
            self.assertTrue(wildfire_lookup.format_report(data).startswith(f'{count} AQI observation{"" if count == 1 else "s"}.'))
            if count:
                data = dict(query=dict(command='fires'), sources=[], incidents=[incident] * count)
                self.assertIn(f'{count} incident {noun}', wildfire_lookup.format_report(data))

    def test_qualifiers_stay_whole_at_field_boundaries(self):
        for value in ('time 1 hr (3 mph; terrain excluded)',
                      'dogs Yes (limited [day; night]; no exceptions)',
                      'station (east | west)'):
            separator = ' | ' if ' | ' in value else '; '
            self.assertEqual(response_text.split_fields(value + separator + 'Other', separator), [value, 'Other'])
        self.assertEqual(response_text.split_fields('name (unfinished; qualifier'), ['name (unfinished; qualifier'])
        field = 'estimate (3 mph | terrain excluded)'
        text = response_text.compact_fields('Status unknown.', [field])
        for sender in ('Alice', 'a' * 80, '温' * 26):
            output = responder.reply_parts(sender, text, max_parts=1)[0]
            self.assertEqual(output.count('('), output.count(')'))
            if '3 mph' in output:
                self.assertIn(field, output)
            self.assertLessEqual(len(output.encode()), 150)

    def test_firedata_labels_and_units_preserve_zero_and_unknown(self):
        labels = {'aqi': 'AQI observation', 'raws': 'RAWS observation',
                  'cameras': 'camera', 'history': 'historical fire', 'treatments': 'fuel treatment',
                  'spc': 'SPC outlook', 'viirs': 'VIIRS detection', 'modis': 'MODIS detection',
                  'potential': 'fire potential record', 'smoke': 'smoke forecast',
                  'aqi_today': 'AQI forecast', 'aqi_tomorrow': 'AQI forecast'}
        for category, label in labels.items():
            for count in (0, 1, 2):
                data = dict(query=dict(command='firedata', category=category), sources=[dict(stale=True)],
                            features=[dict(id='fixture', properties={})] * count)
                text = wildfire_lookup.format_report(data)
                self.assertTrue(text.startswith(response_text.counted(count, label)))
                self.assertIn('Data limited.', text)
                self.assertLessEqual(len(('@Reader ' + text).encode()), 150)
        text = wildfire_lookup.context_line('raws', dict(properties=dict(
            StationName='Oak', RelativeHumidity=0, WindSpeedMPH=0, WindSpeedPeak=0)))
        for phrase in ('RH 0%', 'wind 0 mph', 'gust 0 mph', 'observed unknown'):
            self.assertIn(phrase, text)
        self.assertIn('wind not reported', wildfire_lookup.context_line('raws', dict(properties={})))
        for value, expected in ((True, 'online'), (False, 'offline'), (None, 'status unknown')):
            self.assertEqual(wildfire_lookup.context_line('cameras', dict(properties=dict(cameraName='Oak', isOnline=value))), 'Oak: ' + expected)
        text = wildfire_lookup.context_line('history', dict(properties=dict(Name='Oak Fire', Year=2020)))
        self.assertEqual(text, 'Oak Fire; year: 2020')
        text = wildfire_lookup.context_line('aqi_today', dict(properties=dict(MaxAQI=75, MaxAQICat='Moderate')))
        self.assertIn('max AQI 75 (Moderate); valid time unavailable.', text)

    def test_whole_identical_fields_are_not_repeated(self):
        text = response_text.compact_fields('Status unknown.', ['Status unknown.', 'Location', 'Location'])
        self.assertEqual(text, 'Status unknown. | Location')

    def test_near_fire_prioritizes_distance_over_id_without_losing_uncertainty(self):
        incident_id = '11111111-1111-4111-8111-111111111111'
        incident = dict(name='Near Fire', containment=None, acres=None,
                        display_id=incident_id, distance_miles=0.53)
        for distance in (0.53, None):
            for stale in (False, True):
                data = dict(query=dict(command='fires', radius=2),
                            sources=[dict(stale=stale)], incidents=[dict(incident, distance_miles=distance)])
                for sender in ('Alice', 'a' * 80, '温' * 26):
                    with self.subTest(distance=distance, stale=stale, sender=sender), patch.dict(os.environ, {'MESHCORE_SENDER': sender}):
                        text = wildfire_lookup.format_report(data)
                        parts = responder.reply_parts(sender, text, max_parts=1)
                        self.assertEqual(len(parts), 1)
                        self.assertLessEqual(len(parts[0].encode()), 150)
                        self.assertIn('contained unknown', text)
                        if stale:
                            self.assertIn('Data limited.', text)
                        self.assertNotIn(incident_id, text)
                        if sender == 'Alice':
                            self.assertIn('0.53 mi map distance' if distance is not None else 'Map distance unknown', text)
                            self.assertIn('acres unknown', text)
                        self.assertEqual(data['incidents'][0]['display_id'], incident_id)

    def test_counted_zero_singular_plural_and_irregular_nouns(self):
        for noun, plural in (('station', 'stations'), ('hazard window', 'hazard windows'),
                             ('incident record', 'incident records'), ('NWS alert', 'NWS alerts'),
                             ('basin level', 'basin levels'), ('reach', 'reaches')):
            for count in (0, 1, 2):
                self.assertEqual(response_text.counted(count, noun, plural),
                                 f'{count} {noun if count == 1 else plural}')

    def test_documented_examples_cover_commands_and_fit_radio_budget(self):
        root = Path(__file__).resolve().parents[1]
        document = (root / 'RESPONSE_EXAMPLES.md').read_text(encoding='utf-8')
        examples = re.findall(r'### (![^\n]+)\n\n(\d+) UTF-8 bytes\.\n\n```text\n([^`]+)\n```', document)
        commands = json.loads((root / 'config.json').read_text())['responder']['commands']
        self.assertEqual({command.split()[0] for command, _, _ in examples}, set(commands))
        self.assertEqual({command.split()[0] for command, _, _ in examples if ' near ' in command},
                         {'!trail', '!rec', '!peak', '!park', '!boundary', '!fires', '!slideinfo'})
        for command, size, body in examples:
            with self.subTest(command=command):
                self.assertEqual(int(size), len(body.encode()))
                self.assertLessEqual(len(body.encode()), 150)
                self.assertTrue(body.startswith('@Alice '))
                self.assertNotRegex(body, r'\b1 (stations|hazard windows|incident records|basin levels|NWS alerts)\b')
                self.assertNotIn('Unable to return', body)
                self.assertNotIn('Closest, map distance:', body)
                self.assertNotIn('Mapped areas: inside', body)
                if command.startswith('!fires near '):
                    self.assertIn('map distance', body)
                    self.assertNotRegex(body, r'\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b')
                if command.startswith('!slideinfo'):
                    self.assertNotIn('...', body)


if __name__ == '__main__':
    unittest.main()
