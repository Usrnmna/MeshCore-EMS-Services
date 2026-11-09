"""Offline publication contracts shared by flood and USGS maintenance tools."""

from pathlib import Path
import tempfile
import unittest

from data.flood_impacts import archive


# These are the generation kinds used by the existing maintenance callers.
GENERATION_KINDS = (
    "static", "observations", "inventory", "network", "routing",
    "link_review", "agency_review", "local_review",
)


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def candidate(self, kind):
        """Create a small isolated candidate without acquiring provider data."""
        stage, identifier = archive.begin(self.root, kind)
        archive.write_json(stage / "record.json", {"station_id": "USGS-00123456"})
        return stage, identifier

    def test_existing_generation_kinds_publish_and_verify_independently(self):
        pointers = {}
        for kind in GENERATION_KINDS:
            with self.subTest(kind=kind):
                stage, identifier = self.candidate(kind)
                target, manifest = archive.publish(self.root, stage, identifier, kind, {})
                self.assertEqual(archive.open_generation(self.root, kind), (target, manifest))
                self.assertEqual(manifest["kind"], kind)
                self.assertEqual(manifest["generation"], identifier)
                self.assertEqual(archive.read_json(target / "record.json"),
                                 {"station_id": "USGS-00123456"})
                for previous, content in pointers.items():
                    self.assertEqual((self.root / previous).read_bytes(), content)
                pointers[kind + ".json"] = (self.root / (kind + ".json")).read_bytes()
                (target / "record.json").write_text("tampered", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "checksum"):
                    archive.open_generation(self.root, kind)

    def test_detached_candidates_preserve_every_existing_pointer(self):
        for kind in GENERATION_KINDS:
            with self.subTest(kind=kind):
                stage, identifier = self.candidate(kind)
                active, _ = archive.publish(self.root, stage, identifier, kind, {})
                pointer = self.root / (kind + ".json")
                original = pointer.read_bytes()
                stage, identifier = self.candidate(kind)
                detached, _ = archive.publish(self.root, stage, identifier, kind, {}, activate=False)
                self.assertNotEqual(detached, active)
                self.assertTrue((detached / "manifest.json").is_file())
                self.assertEqual(pointer.read_bytes(), original)
                self.assertEqual(archive.open_generation(self.root, kind)[0], active)

    def test_validator_tampering_keeps_water_inventory_active(self):
        stage, identifier = self.candidate("inventory")
        archive.publish(self.root, stage, identifier, "inventory", {})
        pointer = self.root / "inventory.json"
        original = pointer.read_bytes()
        stage, identifier = self.candidate("inventory")

        def tamper(candidate, manifest):
            """Simulate a validator incorrectly modifying a sealed artifact."""
            archive.write_json(candidate / "record.json", {"station_id": "changed"})

        with self.assertRaisesRegex(ValueError, "Candidate changed"):
            archive.publish(self.root, stage, identifier, "inventory", {}, validator=tamper)
        self.assertEqual(pointer.read_bytes(), original)
        archive.open_generation(self.root, "inventory")

    def test_wrong_kind_or_pending_identity_cannot_publish(self):
        stage, identifier = self.candidate("inventory")
        for kind, generation in (("network", identifier), ("unknown", identifier),
                                 ("../inventory", identifier), ("inventory", "different")):
            with self.subTest(kind=kind, generation=generation):
                with self.assertRaisesRegex(ValueError, "isolated pending generation"):
                    archive.publish(self.root, stage, generation, kind, {})
                self.assertFalse((stage / "manifest.json").exists())
        self.assertEqual(list(self.root.glob("*.json")), [])


if __name__ == "__main__":
    unittest.main()
