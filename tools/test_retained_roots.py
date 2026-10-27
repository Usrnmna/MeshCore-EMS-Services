"""Advisory retained-root discovery requires real registry and receipt evidence."""
from contextlib import nullcontext
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from installers.datasets import manage
from installers.desktop import retained_roots


class RetainedRootsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.hints = self.base / "retained-roots"; self.hints.mkdir()
        self.root = self.base / "retained custom data"
        self.root.mkdir()
        self.trust = patch.object(retained_roots, "_protected_hints", side_effect=lambda path: nullcontext())
        self.trust.start(); self.addCleanup(self.trust.stop)

    def retained(self, dataset="ebmud"):
        relative = f".datasets/{dataset}/fixture/content"
        content = self.root / relative; content.mkdir(parents=True)
        (content / "reference.txt").write_text("isolated reference\n")
        record = {"path": relative, "receipt": f".datasets/{dataset}/fixture/receipt.json"}
        receipt = {"schema": 1, "dataset": dataset, "path": relative,
                   "files": manage.inventory(content), "dependencies": {}}
        (self.root / record["receipt"]).write_text(json.dumps(receipt))
        value = manage.registry(self.root)
        value["datasets"][dataset] = {"active": record, "previous": None}
        (self.root / "datasets.json").write_text(json.dumps(value))
        (self.hints / (dataset + ".txt")).write_text(str(self.root) + "\n")
        return record

    def test_missing_storage_is_not_created_by_discovery(self):
        missing = self.base / "missing"
        self.assertEqual(retained_roots.discover(directory=missing), [])
        self.assertFalse(missing.exists())

    def test_hint_alone_does_not_establish_installation_or_ownership(self):
        (self.hints / "ebmud.txt").write_text(str(self.root))
        self.assertEqual(retained_roots.discover(directory=self.hints), [])
        self.assertFalse((self.root / "datasets.json").exists())

    def test_verified_hints_are_grouped_without_changing_registry(self):
        self.retained("ebmud"); self.retained("wildfire")
        before = (self.root / "datasets.json").read_bytes()
        values = retained_roots.discover(directory=self.hints)
        self.assertEqual(len(values), 1)
        self.assertEqual(values[0]["root"], str(self.root.resolve()))
        self.assertEqual(values[0]["datasets"], ["ebmud", "wildfire"])
        self.assertIn("verified", values[0]["verification"])
        self.assertEqual((self.root / "datasets.json").read_bytes(), before)

    def test_damaged_registry_or_modified_bytes_are_not_claimed_verified(self):
        self.retained()
        (self.root / "datasets.json").write_text("damaged")
        self.assertEqual(retained_roots.discover(directory=self.hints), [])
        (self.root / "datasets.json").unlink()
        self.retained("wildfire")
        (self.root / ".datasets/wildfire/fixture/content/reference.txt").write_text("modified")
        self.assertEqual(retained_roots.discover(directory=self.hints), [])

    def test_unreadable_hint_requires_authorized_discovery(self):
        self.retained()
        with patch.object(retained_roots, "_read_hint", side_effect=PermissionError("protected hint")):
            with self.assertRaises(PermissionError):
                retained_roots.discover(directory=self.hints)

    def test_hint_dataset_must_match_actual_receipt(self):
        record = self.retained()
        receipt = self.root / record["receipt"]
        value = json.loads(receipt.read_text()); value["dataset"] = "wildfire"
        receipt.write_text(json.dumps(value))
        self.assertEqual(retained_roots.discover(directory=self.hints), [])

    def test_relative_and_multiline_hints_are_rejected(self):
        for text in ("relative", str(self.root) + "\nother-root", ""):
            (self.hints / "ebmud.txt").write_text(text)
            self.assertEqual(retained_roots.discover(directory=self.hints), [])


if __name__ == "__main__":
    unittest.main()
