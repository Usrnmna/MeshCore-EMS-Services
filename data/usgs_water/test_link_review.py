"""Evidence gates for supplemental station addresses and current-only integration."""

from copy import deepcopy
from unittest.mock import Mock, patch
import unittest

from shapely.geometry import LineString, Point, mapping

from data.usgs_water import link_review as review
from data.usgs_water.test_usgs_water import workspace


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.sid = "USGS-00123456"
        point = mapping(Point(-122, 38))
        self.station = {"id": self.sid, "geometry": point,
                        "properties": {"monitoring_location_name": "Test Creek", "site_type": "Stream"}}
        self.state = {"id": 1, "geometry": point, "properties": {
            "siteid": "00123456", "operator": "USGS", "comid_medres": "123", "rchcd_medres": "18000000000001"}}
        self.sb = {"id": "00123456", "geometry": point, "properties": {
            "site_id": "00123456", "operator": "USGS", "datasource": "NWIS",
            "provider": "https://waterdata.usgs.gov",
            "weblink": "https://geoconnex.us/usgs/monitoring-location/00123456",
            "comid_medres": 123.0, "rchcd_medres": "18000000000001"}}
        self.indexed = {"reachcode": "18000000000001", "feature_type": "StreamRiver", "collection": "network",
                        "enabled": 1, "flow_direction": "With Digitized",
                        "geometry": mapping(LineString([(-122, 37.999), (-122, 38.001)]))}

    def assess(self, primary=(), state=None, sb=None, indexed=None):
        return review.assess_station(self.station, list(primary), [], state if state is not None else [self.state],
                                     sb if sb is not None else [self.sb], lambda rid: indexed or self.indexed)[0]

    def test_agreeing_identity_and_keys_support_routing_without_observation_values(self):
        result = self.assess()
        self.assertEqual(result["status"], "supported_supplemental_routing")
        self.assertEqual(result["station_id"], "USGS-00123456")
        self.assertFalse({"value", "stage", "discharge", "time_series_id"}.intersection(result))

    def test_agency_identity_disagreement_blocks_even_coincident_geometry(self):
        self.sb["properties"]["operator"] = "CDEC"
        self.assertEqual(self.assess()["status"], "catalog_identity_conflict")

    def test_published_comid_disagreement_stays_explicit(self):
        self.sb["properties"]["comid_medres"] = 456
        self.assertEqual(self.assess()["status"], "conflicting_published_addresses")

    def test_same_comid_with_wrong_network_reachcode_is_not_promoted(self):
        self.indexed["reachcode"] = "18000000000999"
        self.assertEqual(self.assess()["status"], "reachcode_conflict")

    def test_conflicting_reference_address_is_not_ignored(self):
        reference = {"properties": {"provider_id": self.sid, "provider": "https://waterdata.usgs.gov",
                                    "nhdpv2_comid": 456, "nhdpv2_reachcode": None}}
        result, rows = review.assess_station(self.station, [], [reference], [self.state], [self.sb],
                                           lambda rid: self.indexed)
        self.assertEqual(result["status"], "reference_address_conflict")
        self.assertEqual(rows[0]["reach_id"], "456")

    def test_primary_coastline_is_not_reassigned_to_a_nearby_river(self):
        coastal = {**self.indexed, "feature_type": "Coastline"}
        primary = [{"properties": {"identifier": self.sid, "comid": 123}}]
        self.assertEqual(self.assess(primary=primary, indexed=coastal)["status"], "coastline_not_river_routing")

    def test_nonnetwork_address_never_establishes_downstream_flow(self):
        self.indexed.update(collection="nonnetwork", enabled=None, flow_direction="Uninitialized")
        self.assertEqual(self.assess()["status"], "supported_nonnetwork_address_no_downstream")

    def test_large_station_relocation_requires_review(self):
        self.station["geometry"] = mapping(Point(-121, 38))
        self.assertEqual(self.assess()["status"], "spatial_consistency_requires_review")

    def test_no_catalog_record_cannot_be_filled_by_nearest_geometry(self):
        lookup = Mock()
        result, _ = review.assess_station(self.station, [], [], [], [], lookup)
        self.assertEqual(result["status"], "no_corroborated_published_address")
        lookup.assert_not_called()

    def test_ambiguous_identity_is_not_collapsed(self):
        self.assertEqual(self.assess(state=[self.state, deepcopy(self.state)])["status"], "ambiguous_catalog_identity")

    def test_new_primary_address_requires_primary_network_refresh(self):
        primary = [{"properties": {"identifier": self.sid, "comid": 123}}]
        self.assertEqual(self.assess(primary=primary)["status"], "primary_address_requires_network_refresh")

    def test_disabled_direction_is_not_promoted(self):
        self.indexed["enabled"] = 0
        self.assertEqual(self.assess()["status"], "network_direction_requires_review")

    def test_overlay_preserves_primary_table_and_rejects_existing_conflict(self):
        with workspace() as root:
            primary = [{"station_id": self.sid, "reach_id": "", "reachcode": ""}]
            extra = {"station_id": self.sid, "reach_id": "123", "reachcode": "code", "source_url": "source",
                     "evidence_class": "published"}
            metadata = {"inventory_pointer": {"id": 1}, "network_pointer": {"id": 2}}
            with patch.object(review.archive, "open_generation", return_value=(root, metadata)), \
                 patch.object(review, "read_csv", side_effect=[deepcopy(primary), [extra]]):
                result, _ = review.effective_links(root, root, {"id": 1}, {"id": 2}, {"id": 3})
            self.assertEqual(result[0]["reach_id"], "123")
            self.assertEqual(primary[0]["reach_id"], "")
            primary[0]["reach_id"] = "999"
            with patch.object(review.archive, "open_generation", return_value=(root, metadata)), \
                 patch.object(review, "read_csv", side_effect=[primary, [extra]]):
                with self.assertRaisesRegex(ValueError, "conflicts"):
                    review.effective_links(root, root, {"id": 1}, {"id": 2}, {"id": 3})

    def test_stale_review_cannot_silently_supplement_a_different_inventory(self):
        with workspace() as root:
            with patch.object(review.archive, "open_generation", return_value=(root, {"inventory_pointer": {"id": 9}})), \
                 patch.object(review, "read_csv", return_value=[]):
                with self.assertRaisesRegex(ValueError, "stale"):
                    review.effective_links(root, root, {"id": 1}, {"id": 2}, {"id": 3})


if __name__ == "__main__":
    unittest.main()
