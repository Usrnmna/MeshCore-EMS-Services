"""Require one executable Python program per shipped MeshCore command."""

import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CommandProgramTests(unittest.TestCase):
    def test_every_command_has_its_own_script(self):
        """Reject missing programs and shared entry points in the default command map."""
        commands = json.loads((ROOT / 'config.json').read_bytes())['responder']['commands']
        owners = {}
        for command, spec in commands.items():
            path = ROOT / spec['script']
            with self.subTest(command=command):
                self.assertEqual(path.parent, ROOT / 'scripts')
                self.assertEqual(path.suffix, '.py')
                self.assertTrue(path.is_file())
                self.assertNotIn(path, owners, f'{command} shares a program with {owners.get(path)}')
                owners[path] = command


if __name__ == '__main__':
    unittest.main()
