"""W01 discovery, channel isolation, and bounded input regression tests."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sqlite3
import time
import sys
import unittest
import tempfile
from unittest.mock import AsyncMock, patch

from scripts.command_dependencies import dependency_status, is_bundled

import responder

ROOT = Path(__file__).resolve().parents[1]


class HelpTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))["responder"]
        self.spec = self.config["commands"]["!help"]

    def test_shipped_configuration_validates(self):
        responder.validate_config(self.config, ROOT)

    async def test_other_channel_does_not_discover_default_commands(self):
        self.config["commands"]["!help"]["channels"].append("other")
        request = {"command": "!help", "arguments": ["!time"], "sender": "Alice",
                   "channel_name": "other", "channel_id": "other", "channel_index": 4,
                   "id": "2", "phrase": "!help !time"}
        output, _ = await responder.run_script(ROOT, self.spec, request, self.config)
        self.assertIn("unavailable on this channel", output)
        request["arguments"] = ["service"]
        output, _ = await responder.run_script(ROOT, self.spec, request, self.config)
        self.assertIn("!help", output)
        self.assertNotIn("!time", output)
        self.assertNotIn("!status", output)

    def test_query_is_literal_and_bounded(self):
        commands = self.config["commands"]
        self.assertEqual(responder.match_command("!help --version", commands), ("!help", ["--version"], None))
        self.assertIsNotNone(responder.match_command("!help " + "é" * 76, commands)[2])
        self.assertIsNotNone(responder.match_command("!help x\x00y", commands)[2])
        self.assertEqual(responder.match_command("!help", commands), ("!help", [""], None))
        now = int(time.time())
        request = responder.parse_message({"channel_idx": 3, "txt_type": 0,
            "text": "Alice: !help x\t", "sender_timestamp": now}, 3, "Bot", self.config, now)
        self.assertIsNotNone(request["input_error"])

    async def test_filtered_catalog_and_private_configuration(self):
        self.config["commands"]["!status"]["channels"] = []
        self.config["commands"]["!time"]["secret"] = "SECRET_VALUE"
        request = {"command": "!help", "arguments": ["!status"], "sender": "Alice",
                   "channel_name": "test", "channel_id": "default", "channel_index": 3,
                   "id": "1", "phrase": "!help !status"}
        output, detail = await responder.run_script(ROOT, self.spec, request, self.config)
        self.assertIn("unavailable", output)
        self.assertNotIn("SECRET_VALUE", output + detail)
        request["arguments"] = ["!time"]
        output, detail = await responder.run_script(ROOT, self.spec, request, self.config)
        self.assertIn("!time", output)
        self.assertNotIn("SECRET_VALUE", output + detail)

    async def test_topic_output_and_standalone(self):
        request = {"command": "!help", "arguments": ["parks"], "sender": "Alice",
                   "channel_name": "test", "channel_id": "default", "channel_index": 3,
                   "id": "1", "phrase": "!help parks"}
        output, detail = await responder.run_script(ROOT, self.spec, request, self.config)
        self.assertIn("!trail", output)
        self.assertLessEqual(len(("@Alice " + output.strip()).encode()), 150)
        env = os.environ.copy()
        env.pop("MESHCORE_HELP_COMMANDS", None)
        result = subprocess.run([sys.executable, str(ROOT / "scripts" / "command_help.py")],
                                capture_output=True, text=True, env=env, check=True)
        self.assertIn("availability unknown", result.stdout)


    def help_output(self, query, catalog, sender="Alice"):
        """Execute the actual program with bounded, non-secret service context."""
        env = dict(os.environ, MESHCORE_HELP_COMMANDS=json.dumps(catalog), MESHCORE_SENDER=sender)
        result = subprocess.run([sys.executable, str(ROOT / "scripts" / "command_help.py"), query],
                                capture_output=True, text=True, env=env, check=True)
        self.assertLessEqual(len(("@" + sender + " " + result.stdout.strip()).encode()), 150)
        return result.stdout

    def test_credential_unavailable_and_provider_unverified(self):
        with patch.dict(os.environ, {"AIRNOW_API_KEY": ""}):
            self.assertIn("Unavailable", self.help_output("!aqi", {"!aqi": True}))
            self.assertIn("unavailable", self.help_output("weather", {"!aqi": True}))
        with patch.dict(os.environ, {"AIRNOW_API_KEY": "SENSITIVE_KEY"}):
            output = self.help_output("!aqi", {"!aqi": True})
            self.assertIn("Provider unverified", output)
            self.assertNotIn("SENSITIVE_KEY", output)
        self.assertIn("Local command", self.help_output("!status", {"!status": True}))

    def test_managed_removal_and_invalid_registry_are_not_ready(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {"MESHCORE_DATA_DIR": folder}):
            registry = Path(folder) / "datasets.json"
            registry.write_text(json.dumps({"schema": 1, "datasets": {"ebmud": {"active": None}}}))
            self.assertIn("Unavailable", dependency_status("!rec"))
            registry.write_text("broken registry")
            self.assertIn("Unavailable", dependency_status("!rec"))

    def test_gis_integrity_and_generation_checks(self):
        from scripts.gis_data import load_settings
        settings = load_settings()
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            raw = json.dumps({"type": "FeatureCollection", "features": [{"type": "Feature",
                "properties": {"LABEL": "Test"}, "geometry": {"type": "Point", "coordinates": [-122, 38]}}]}).encode()
            (directory / "rec.json").write_bytes(raw)
            (directory / "sources.json").write_text(json.dumps({"datasets": {"recreation_points": {
                "path": "rec.json", "byte_count": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "feature_count": 1}}}))
            settings["data_directory"] = directory
            with patch("scripts.gis_data.load_settings", return_value=settings):
                self.assertIn("Local data checked", dependency_status("!rec"))
                (directory / "rec.json").write_text("corrupt")
                self.assertIn("Unavailable", dependency_status("!rec"))

    def test_disabled_feature_missing_cache_and_partial_water(self):
        with patch.dict(os.environ, {"MESHCORE_LANDSLIDE_SETTINGS": '{"enabled": false}'}):
            self.assertIn("disabled", dependency_status("!slideinfo"))
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {
            "MESHCORE_RUNTIME_DIR": folder, "MESHCORE_WILDFIRE_SETTINGS": '{}',
            "MESHCORE_WATER_SETTINGS": json.dumps({"data_directory": folder})}):
            self.assertIn("Unavailable", dependency_status("!fires"))
            self.assertFalse((Path(folder) / "wildfire.sqlite3").exists())
            self.assertIn("Partial", dependency_status("!waterway"))
            self.assertEqual(dependency_status("!floodwarn"), "Provider unverified")

    def test_replaced_and_custom_programs_are_unverified(self):
        self.assertEqual(dependency_status("!rec", False), "Dependencies unverified")
        output = self.help_output("!rec", {"!rec": False})
        self.assertIn("Dependencies unverified", output)
        self.assertNotIn("Local data checked", output)
        self.assertIn("!custom", self.help_output("other", {"!custom": False}))

    async def test_help_request_is_processed_and_tagged_on_origin_channel(self):
        send = AsyncMock()
        db = sqlite3.connect(":memory:")
        try:
            with patch.dict(os.environ, {"AIRNOW_API_KEY": ""}):
                bot = responder.Responder(ROOT, db, self.config, 3, "Local Bot", send)
                self.assertTrue(bot.accept({"channel_idx": 3, "txt_type": 0,
                    "text": "Alice: !help !aqi", "sender_timestamp": int(time.time())}))
                self.assertTrue(await bot.process_one())
            send.assert_awaited_once()
            channel, text = send.await_args.args
            self.assertEqual(channel, 3)
            self.assertTrue(text.startswith("@Alice !aqi: Unavailable"))
            self.assertIn("!aqi LAT LON", text)
            self.assertLessEqual(len(text.encode()), 150)
        finally:
            db.close()

    def test_registration_changes_do_not_get_shipped_syntax_or_status(self):
        for name, spec in self.config["commands"].items():
            self.assertTrue(is_bundled(name, spec), name)
        for key, value in (("input", "none"), ("args", ["--custom"]),
                           ("script", "programs/custom.py"), ("coordinate_style", "options")):
            changed = dict(self.config["commands"]["!rec"], **{key: value})
            self.assertFalse(is_bundled("!rec", changed))
        output = self.help_output("!rec", {"!rec": False})
        self.assertNotIn("Recreation amenities", output)

    def test_empty_wildfire_cache_is_unavailable_without_mutation(self):
        from scripts.wildfire_store import Store
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {
                "MESHCORE_RUNTIME_DIR": folder, "MESHCORE_WILDFIRE_SETTINGS": '{}'}):
            path = Path(folder) / "wildfire.sqlite3"
            with Store(path, writable=True):
                pass
            before = path.read_bytes()
            self.assertIn("uninitialized", dependency_status("!fires"))
            self.assertEqual(path.read_bytes(), before)

    def test_specific_syntax_survives_maximum_sender(self):
        catalog = {name: True for name in self.config["commands"]}
        with patch.dict(os.environ, {"AIRNOW_API_KEY": ""}):
            for name in ("!aqi", "!floodalarm", "!slidealarm", "!firealarm", "!boundary"):
                output = self.help_output(name, catalog, "é" * 40)
                self.assertIn(" | " + name + " ", output, name)
            self.assertIn("Unavailable", self.help_output("!aqi", catalog, "é" * 40))

    def test_leading_controls_cannot_shift_query_validation(self):
        now = int(time.time())
        for phrase in ("\t!help", "\n!help service", "!help service\t", "!help x\x00y"):
            request = responder.parse_message({"channel_idx": 3, "txt_type": 0,
                "text": "Alice: " + phrase, "sender_timestamp": now}, 3, "Bot", self.config, now)
            self.assertIsNotNone(request["input_error"], repr(phrase))

    def test_budget_malformed_context_and_control_inputs(self):
        catalog = {name: True for name in self.config["commands"]}
        for query in ("", "parks", "fire", "water", "satellites", "!floodalarm", "!boundary", "--version", "x;echo secret"):
            self.help_output(query, catalog, "é" * 40)
        self.assertIn("unavailable", self.help_output("", []))
        self.assertIn("Invalid", self.help_output("bad\nquery", catalog))
        self.assertIsNotNone(responder.match_command("!help x\t", self.config["commands"])[2])
        self.assertIsNone(responder.match_command("!help " + "é" * 75, self.config["commands"])[2])


if __name__ == "__main__":
    unittest.main()
