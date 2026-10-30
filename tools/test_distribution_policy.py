"""Protect local-reference exclusions at collection, staging and archive boundaries."""

from pathlib import Path
import io
import json
import shutil
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import artifact_provenance
import build_data_installers as datasets
import build_dataset_gui as gui
import build_installers as services
import package_services
import build_documentation
from distribution_policy import is_local_reference, validate_tree


class DistributionPolicyTests(unittest.TestCase):
    def test_all_collectors_exclude_planning_and_keep_required_inputs(self):
        groups = (services.source_files(), gui.source_files(),
                  [ROOT / name for name in datasets.source_inventory()])
        for paths in groups:
            names = [path.relative_to(ROOT).as_posix() for path in paths]
            self.assertFalse(any(map(is_local_reference, names)))
            self.assertIn("docs/DATA_PACKAGES.md", names)
        self.assertIn(ROOT / "installers/desktop/history_process.py", gui.source_files())
        self.assertIn(ROOT / "meshcore_mqtt_service/channel_history.py", services.source_files())

    def test_provenance_and_final_tree_reject_reintroduced_planning(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source/docs/superpowers/specs/local.md"
            source.parent.mkdir(parents=True)
            source.write_text("local fixture")
            with self.assertRaises(ValueError):
                artifact_provenance.source_hashes([source], root)
            with self.assertRaises(ValueError):
                validate_tree(root)

    def test_path_policy_is_case_and_separator_independent(self):
        for name in ("docs/superpowers/a.md", "source/DOCS/Superpowers/a.md",
                     r"docs\superpowers\specs\a.md"):
            self.assertTrue(is_local_reference(name))
        self.assertFalse(is_local_reference("docs/CHANNEL_HISTORY_VERIFICATION.md"))
        self.assertFalse(is_local_reference("tools/test_distribution_policy.py"))

    def test_packaged_data_links_are_paths_without_changing_source_inventory_rows(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "data/ebmud/README.md"
            source.parent.mkdir(parents=True)
            original = "# Dataset\n\n[Reference](organized/reference.json)\n"
            source.write_text(original)
            rendered = build_documentation.render_document(source, root, {source})
            self.assertIn("Reference (`organized/reference.json`)", rendered)
            self.assertIn("separately installed data", rendered)
            self.assertEqual(source.read_text(), original)

    def test_build_collection_staging_and_archives_without_planning_directory(self):
        """Exercise real recipes against a disposable, planning-free source tree."""
        with tempfile.TemporaryDirectory() as folder:
            temporary = Path(folder)
            snapshot = temporary / "source"
            for path in services.source_files():
                destination = snapshot / path.relative_to(ROOT)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, destination)
            self.assertFalse((snapshot / "docs/superpowers").exists())
            with patch.object(services, "ROOT", snapshot), patch.object(package_services, "ROOT", snapshot), \
                    patch.object(gui, "ROOT", snapshot), patch.object(datasets, "ROOT", snapshot):
                service_stage = temporary / "service-stage"
                services.stage_payload(service_stage)
                self.assertTrue(gui.source_hashes())
                data_stage = temporary / "data-stage"
                datasets.stage_payload(data_stage, "basin_plans", root=snapshot)
                output = temporary / "outputs"
                output.mkdir()
                archives = [services.linux_installer(service_stage, output, "x86_64"),
                            datasets.linux_installer(data_stage, output, "basin_plans", "linux-x86_64")]
            for stage in (service_stage, data_stage):
                validate_tree(stage)
                manifest = json.loads((stage / "PAYLOAD-MANIFEST.json").read_text())
                self.assertFalse(any(map(is_local_reference, manifest["files"])))
            for archive in archives:
                raw = archive.read_bytes()
                # Both self-extractors have a gzip payload after their shell header.
                offset = raw.index(b"\x1f\x8b\x08")
                with tarfile.open(fileobj=io.BytesIO(raw[offset:]), mode="r:gz") as packed:
                    self.assertFalse(any(map(is_local_reference, packed.getnames())))


if __name__ == "__main__":
    unittest.main()
