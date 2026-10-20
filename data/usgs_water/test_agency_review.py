"""Tests for original-agency exclusions, static identities and source parsing."""

from copy import deepcopy
import hashlib
import io
import struct
import unittest
from unittest.mock import Mock
import zipfile

from shapely.geometry import Point, LineString, mapping

from data.usgs_water.agency_review import assess, check_swim_archive, dbf_rows


class AgencyReviewTests(unittest.TestCase):
    def setUp(self):
        self.sid = "USGS-00123456"
        self.station = {"id": self.sid, "geometry": mapping(Point(-122, 38)),
                        "properties": {"agency_code": "USGS", "monitoring_location_number": "00123456",
                                       "monitoring_location_name": "Example Canal"}}
        self.prior = {"status": "no_corroborated_published_address"}
        self.gage = {"SOURCE_FEA": "00123456", "SOURCE_ORI": "USGS, Water Resources Division",
                     "EventType": "StreamGage", "COMID": "0", "FLComID": "123",
                     "REACHCODE": "18000000000001", "EVENTDATE": "20141204"}
        self.feature = {"reachcode": "18000000000001", "collection": "nonnetwork",
                        "geometry": mapping(LineString([(-122, 37.99), (-122, 38.01)]))}

    def run_case(self, gages=None, swim=None, candidates=None):
        return assess(self.station, self.prior, [self.gage] if gages is None else gages,
                      swim or [], candidates or [], lambda rid: self.feature)

    def test_flowline_field_is_used_instead_of_zero_event_comid(self):
        result = self.run_case()
        self.assertEqual(result["reach_id"], "123")
        self.assertEqual(result["status"], "supported_static_nonnetwork_address")
        self.assertIs(result["routing_supported"], False)

    def test_wrong_wasteway_location_vetoes_legacy_address(self):
        result = self.run_case(swim=[{"QC_final": "Drop", "Ver_notes3":
                              "Drop. Canal Wasteway site should be on wasteway diversion from canal"}])
        self.assertEqual(result["status"], "agency_rejects_legacy_address")
        self.assertEqual(result["reach_id"], "")

    def test_wrong_diversion_connections_are_never_routed(self):
        result = self.run_case(swim=[{"QC_final": "Drop", "QC_notes1":
                              "GageLoc is also wrong (wrong location and wrong connections)."}])
        self.assertEqual(result["status"], "agency_rejects_legacy_address")

    def test_conflicting_catalog_requires_agency_key_agreement(self):
        self.prior["status"] = "conflicting_published_addresses"
        candidates = [{"source": "sb19", "reach_id": "999", "reachcode": self.gage["REACHCODE"]}]
        self.assertEqual(self.run_case(candidates=candidates)["status"], "conflicting_agency_and_catalog_addresses")
        candidates[0]["reach_id"] = "123"
        self.assertEqual(self.run_case(candidates=candidates)["status"], "supported_static_nonnetwork_address")

    def test_far_old_address_is_explicit(self):
        self.station["geometry"] = mapping(Point(-121, 38))
        self.assertEqual(self.run_case()["status"], "agency_address_spatial_mismatch")

    def test_network_address_is_not_automatically_promoted(self):
        self.feature["collection"] = "network"
        result = self.run_case()
        self.assertEqual(result["status"], "agency_network_address_requires_review")
        self.assertEqual(result["reach_id"], "")

    def test_multiple_original_records_are_ambiguous(self):
        self.assertEqual(self.run_case(gages=[self.gage, deepcopy(self.gage)])["status"], "ambiguous_agency_records")

    def test_no_record_and_documented_exclusion_are_distinct(self):
        self.assertEqual(self.run_case(gages=[])["status"], "no_published_agency_address_found")
        self.assertEqual(self.run_case(gages=[], swim=[{"QC_final": "Drop", "Ver_notes3": "No NHDPlus feature"}])["status"],
                         "agency_documents_network_limitation")

    def test_bad_source_keys_are_withheld(self):
        self.gage["FLComID"] = "-9999"
        self.assertEqual(self.run_case()["status"], "missing_agency_address_keys")
        self.gage["FLComID"] = "123"
        self.feature["reachcode"] = "18000000000999"
        self.assertEqual(self.run_case()["status"], "agency_feature_key_conflict")

    def test_missing_address_does_not_trigger_nearest_feature_lookup(self):
        lookup = Mock()
        assess(self.station, self.prior, [], [], [], lookup)
        lookup.assert_not_called()


class DbaseTests(unittest.TestCase):
    def source(self):
        content = bytearray(65)
        content[0] = 3
        struct.pack_into("<IHH", content, 4, 1, 65, 9)
        content[32:39] = b"Station"
        content[43] = ord("C")
        content[48] = 8
        content[64] = 13
        return bytes(content) + b" 00123456"

    def test_station_leading_zeroes_remain_strings(self):
        self.assertEqual(list(dbf_rows(self.source())), [{"Station": "00123456"}])

    def test_truncated_record_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Truncated"):
            list(dbf_rows(self.source()[:-1]))

    def test_deleted_record_is_rejected(self):
        source = bytearray(self.source())
        source[65] = ord("*")
        with self.assertRaisesRegex(ValueError, "Deleted"):
            list(dbf_rows(source))


class PublisherChecksumTests(unittest.TestCase):
    def archive(self, changed_suffix):
        stream = io.BytesIO()
        entries = []
        with zipfile.ZipFile(stream, "w") as bundle:
            for suffix in (".dbf", ".shp", ".shx", ".prj", "_Metadata.xml"):
                name = "SWIM_gage_loc/SWIM_gage_loc" + suffix
                bundle.writestr(name, b"changed" if suffix == changed_suffix else b"source")
                entries.append({"name": name, "size": 6, "checksum":
                                {"type": "MD5", "value": hashlib.md5(b"source").hexdigest()}})
        stream.seek(0)
        return zipfile.ZipFile(stream), {"distributionLinks": [{"files": entries}]}

    def test_publisher_xml_discrepancy_is_reported_without_weakening_data_checks(self):
        bundle, metadata = self.archive("_Metadata.xml")
        with bundle:
            checks = check_swim_archive(bundle, metadata)
        self.assertEqual([r["status"] for r in checks].count("verified"), 4)
        self.assertEqual(checks[-1]["status"], "publisher_xml_checksum_discrepancy")
        self.assertFalse(checks[-1]["used_for_station_decisions"])

    def test_changed_station_data_fails_closed(self):
        bundle, metadata = self.archive(".dbf")
        with bundle, self.assertRaisesRegex(ValueError, "decision data"):
            check_swim_archive(bundle, metadata)


if __name__ == "__main__":
    unittest.main()
