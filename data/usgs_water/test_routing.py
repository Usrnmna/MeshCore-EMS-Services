"""Routing regression tests: direction, branching, uncertainty and derived basin links."""

from collections import defaultdict
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import Mock, patch

import shapely
from shapely.geometry import LineString, box, mapping

from data.usgs_water import routing
from data.usgs_water.test_usgs_water import workspace


def reach(key, start, end, **changes):
    row = {"reach_id": str(key), "name": f"Waterway {key}", "reachcode": f"code-{key}", "from_node": str(start) if start else "",
           "to_node": str(end) if end else "", "divergence": 0, "terminal": 0, "tidal": 0,
           "flow_direction": "With Digitized", "enabled": 1}
    return {**row, **changes}


class GraphTests(unittest.TestCase):
    def test_both_branches_and_cycle_terminate_with_shortest_hops(self):
        adjacency = {"1": ["2", "3"], "2": ["4"], "3": ["4", "1"], "4": ["5"]}
        self.assertEqual(routing.downstream_hops("1", adjacency), {"1": 0, "2": 1, "3": 1, "4": 2, "5": 3})

    def test_null_nodes_do_not_join_and_terminal_is_not_an_outlet_claim(self):
        rows = routing.graph_rows([reach(1, 10, None), reach(2, None, 20, terminal=1)])
        self.assertTrue(all(not row[1] for row in rows))
        self.assertEqual([row[3] for row in rows], ["unresolved_source_endpoint", "source_terminal"])

    def test_unknown_direction_and_disabled_segments_are_not_routable(self):
        rows = routing.graph_rows([reach(1, 10, 20), reach(2, 20, 30, enabled=0), reach(3, 30, 40, flow_direction="Uninitialized")])
        self.assertEqual(rows[0][3], "direction_or_enabled_requires_review")
        self.assertEqual(rows[1][3], "direction_or_enabled_requires_review")

    def test_terminal_node_connection_is_preserved_without_continuing_the_river_path(self):
        rows = routing.graph_rows([reach(1, 10, 20, terminal=1), reach(2, 20, 30)])
        self.assertEqual(rows[0][1], "2")
        self.assertEqual(rows[0][3], "source_terminal")
        adjacency = defaultdict(list)
        for a, b, _, status, *_ in rows:
            if status == "published_node_connection":
                adjacency[a].append(b)
        self.assertEqual(routing.downstream_hops("1", adjacency), {"1": 0})

    def test_coastline_geometry_does_not_link_unrelated_coastal_basins(self):
        rows = routing.graph_rows([reach(1, 10, 20), reach(2, 20, 30, feature_type="Coastline"), reach(3, 30, 40)])
        self.assertEqual([r[3] for r in rows[:2]], ["coastline_connection_not_river_routing"] * 2)

    def test_offline_rebuild_reuses_only_acquisition_and_spatial_tables(self):
        with workspace() as root:
            previous = root / ".pending-old"
            previous.mkdir()
            old = routing.initialize_database(previous / "routing.download")
            old.execute("INSERT INTO reaches(reach_id,name) VALUES ('1','Published name')")
            old.execute("INSERT INTO station_downstream_reaches VALUES ('station','1',0,'obsolete','derived')")
            old.commit()
            old.close()
            (previous / "routing.download").rename(previous / "routing.sqlite")
            (previous / "raw").mkdir()
            (previous / "raw/source.gz").write_bytes(b"original response bytes")
            stage = root / ".pending-new"
            stage.mkdir()
            db = routing.initialize_database(stage / "routing.download")
            routing.reuse_acquisition(db, previous, stage)
            self.assertEqual(db.execute("SELECT name FROM reaches").fetchone()[0], "Published name")
            self.assertEqual(db.execute("SELECT count(*) FROM station_downstream_reaches").fetchone()[0], 0)
            self.assertEqual((stage / "raw/source.gz").read_bytes(), b"original response bytes")
            db.close()

    def test_confluence_keeps_named_and_unnamed_incoming_branches(self):
        with workspace() as root:
            stage = root / ".pending-test"
            stage.mkdir()
            db = routing.initialize_database(stage / "routing.download")
            rows = [reach(1, 10, 30, name="Tributary"), reach(2, 20, 30, name=""), reach(3, 30, 40, terminal=1)]
            for r in rows:
                db.execute("INSERT INTO reaches(reach_id,name,reachcode,from_node,to_node,divergence,terminal,tidal,flow_direction,enabled) VALUES (?,?,?,?,?,?,?,?,?,?)",
                           tuple(r[k] for k in ("reach_id", "name", "reachcode", "from_node", "to_node", "divergence", "terminal", "tidal", "flow_direction", "enabled")))
            routing.build_graph(db)
            self.assertEqual(db.execute("SELECT count(*) FROM tributary_connections").fetchone()[0], 2)
            self.assertEqual(db.execute("SELECT count(*) FROM tributary_connections WHERE upstream_name=''").fetchone()[0], 1)
            db.close()

    def test_missing_and_mismatched_station_seeds_remain_explicit(self):
        with workspace() as root:
            stage = root / ".pending-test"
            stage.mkdir()
            db = routing.initialize_database(stage / "routing.download")
            routing.build_station_routes(db, [
                {"station_id": "missing", "reach_id": ""}, {"station_id": "absent", "reach_id": "99"},
                {"station_id": "mismatch", "reach_id": "1", "reachcode": "wrong"},
                {"station_id": "coastal", "reach_id": "2", "reachcode": "code-2"}],
                [reach(1, 10, 20), reach(2, 20, 30, feature_type="Coastline")], [])
            states = dict(db.execute("SELECT station_id,status FROM station_routing_coverage"))
            self.assertEqual(states["missing"], "missing_published_station_reach")
            self.assertEqual(states["absent"], "published_station_reach_absent_from_source")
            self.assertEqual(states["mismatch"], "published_reachcode_mismatch_requires_review")
            self.assertEqual(states["coastal"], "coastline_seed_not_river_routing")
            self.assertEqual(db.execute("SELECT count(*) FROM station_downstream_reaches").fetchone()[0], 0)
            db.close()

    def test_basin_links_keep_point_contact_distinct_and_never_predict_inundation(self):
        with workspace() as root:
            stage = root / ".pending-test"
            stage.mkdir()
            db = routing.initialize_database(stage / "routing.download")
            reaches = [reach(1, 10, 20), reach(2, 20, 30, terminal=1, tidal=1)]
            edges = routing.graph_rows(reaches)
            db.executemany("INSERT INTO reach_calwater_overlaps VALUES (?,?,?,?,?)", [
                ("1", "basin-a", 100, "line_overlap", "derived"), ("2", "basin-a", 50, "line_overlap", "derived"),
                ("2", "basin-b", 0, "boundary_touch_only", "derived")])
            routing.build_station_routes(db, [{"station_id": "USGS-01", "reach_id": "1", "reachcode": "code-1"}], reaches, edges)
            rows = list(db.execute("SELECT basin_id,minimum_hops,connected_reach_count,positive_length_reaches,relationship,impact_status FROM station_downstream_basins ORDER BY basin_id"))
            self.assertEqual(rows[0][:4], ("basin-a", 0, 2, 2))
            self.assertEqual(rows[1][4], "boundary_contact_only")
            self.assertTrue(all("not_predicted_inundation" in r[5] for r in rows))
            self.assertEqual(db.execute("SELECT tidal_reaches FROM station_routing_coverage").fetchone()[0], 1)
            db.close()


class AcquisitionTests(unittest.TestCase):
    def test_scope_includes_calwater_and_station_reaches_but_not_unrelated_border_context(self):
        with workspace() as root:
            stage = root / ".pending-test"
            stage.mkdir()
            db = routing.initialize_database(stage / "routing.download")
            for rid, coordinates in [("1", [(0, 0), (1, 1)]), ("2", [(20, 20), (21, 21)]),
                                     ("3", [(30, 30), (31, 31)])]:
                db.execute("INSERT INTO reaches(reach_id,geometry_wkb) VALUES (?,?)",
                           (rid, shapely.to_wkb(LineString(coordinates))))
            manifest = {"datasets": [{"name": "CalWater_Hydrologic_Region"}]}
            with patch.object(routing.reference, "open_snapshot", return_value=(root, manifest)), \
                 patch.object(routing.reference, "iter_snapshot_records", return_value=iter([
                     {"geometry": mapping(box(-1, -1, 2, 2))}])):
                seeds = routing.select_scope_seeds(db, root, [{"reach_id": "3"}])
            self.assertEqual(seeds, {"1", "3"})
            db.close()

    def test_cross_border_closure_keeps_both_branches_and_stops_at_source_terminals(self):
        def feature(rid, start, end, coordinates, terminal=0):
            return {"properties": {"comid": rid, "fromnode": start, "tonode": end,
                                   "terminalfl": terminal}, "geometry": mapping(LineString(coordinates))}

        first = feature(1, 10, 20, [(-124, 42), (-124, 43)])
        branch_a = feature(2, 20, 30, [(-124, 43), (-124, 44)], terminal=1)
        branch_b = feature(3, 20, 40, [(-124, 43), (-123, 44)])
        last = feature(4, 40, 50, [(-123, 44), (-123, 45)], terminal=1)
        predicates = []

        def source_query(client, name, predicate):
            predicates.append(predicate)
            if name == "statewide_envelope":
                yield [first]
            elif predicate == "fromnode IN (20)":
                yield [branch_a, branch_b]
            elif predicate == "fromnode IN (40)":
                yield [last]
            else:
                self.fail(f"Unexpected source query: {predicate}")

        with workspace() as root:
            stage = root / ".pending-test"
            stage.mkdir()
            db = routing.initialize_database(stage / "routing.download")
            with patch.object(routing, "wfs_query", side_effect=source_query), \
                 patch.object(routing, "select_scope_seeds", return_value={"1"}):
                routing.acquire(db, Mock(), [{"reach_id": "1"}], root)
            self.assertEqual({r[0] for r in db.execute("SELECT reach_id FROM reaches")}, {"1", "2", "3", "4"})
            self.assertEqual(len(predicates), 3)
            self.assertEqual({r[0] for r in db.execute("SELECT node_id FROM source_checks")}, {"20", "40"})
            db.close()

    def test_wfs_short_page_continues_to_exact_total(self):
        client = Mock()
        client.fetch.side_effect = [b'<FeatureCollection numberMatched="2"/>',
            {"features": [{"properties": {"comid": 1}}], "numberReturned": 1},
            {"features": [{"properties": {"comid": 2}}], "numberReturned": 1},
            b'<FeatureCollection numberMatched="2"/>']
        self.assertEqual(sum(len(p) for p in routing.wfs_query(client, "test", "comid>0")), 2)

    def test_source_change_or_repeated_page_rejected(self):
        for responses in ([b'<FeatureCollection numberMatched="1"/>', {"features": [{"properties": {"comid": 1}}], "numberReturned": 1}, b'<FeatureCollection numberMatched="2"/>'],
                          [b'<FeatureCollection numberMatched="2"/>', {"features": [{"properties": {"comid": 1}}], "numberReturned": 1}, {"features": [{"properties": {"comid": 1}}], "numberReturned": 1}]):
            client = Mock()
            client.fetch.side_effect = responses
            with self.assertRaises(ValueError):
                list(routing.wfs_query(client, "test", "comid>0"))

    def test_identifier_zero_and_noninteger_do_not_form_keys(self):
        self.assertEqual(routing.identifier(0), "")
        self.assertEqual(routing.identifier(1e7), "10000000")
        with self.assertRaises(ValueError):
            routing.identifier(12.5)


if __name__ == "__main__":
    unittest.main()
