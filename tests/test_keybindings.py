"""Exercise the shortcut viewer helper without running desktop commands."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
BASH = shutil.which("bash")


@unittest.skipUnless(BASH and shutil.which("jq"), "Bash and jq are required")
class KeybindingsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.log = self.base / "calls.jsonl"
        self.bin = self.base / "bin"
        self.bin.mkdir()
        for name in ("omarchy-menu-keybindings", "omarchy-shell", "omarchy-notification-send"):
            stub = self.bin / name
            stub.write_text(f"#!{sys.executable}\n" + '''import json, os, sys
from pathlib import Path
name = Path(sys.argv[0]).name
with open(os.environ['VIEWER_LOG'], 'a') as stream:
    stream.write(json.dumps([name, *sys.argv[1:]]) + '\\n')
if name == 'omarchy-menu-keybindings':
    sys.stdout.write(os.environ['VIEWER_TEXT'])
    sys.exit(int(os.environ.get('VIEWER_EXIT', '0')))
''')
            stub.chmod(0o755)

    def run_viewer(self, text, exit_code=0):
        self.log.unlink(missing_ok=True)
        result = subprocess.run([BASH, str(ROOT / "keybindings")], text=True,
                                capture_output=True, timeout=10, env={
            **os.environ, "PATH": str(self.bin) + os.pathsep + os.environ["PATH"],
            "VIEWER_LOG": str(self.log), "VIEWER_TEXT": text, "VIEWER_EXIT": str(exit_code),
        })
        return result, [json.loads(line) for line in self.log.read_text().splitlines()]

    def test_live_listing_is_data_in_the_filtered_viewer(self):
        marker = self.base / "must-not-exist"
        lines = ["SUPER + K → Keybindings", "ALT + PRINT → Screenrecording",
                 f'SUPER + X → Quotes " and $(touch {marker}) `false`']
        result, calls = self.run_viewer("\n".join(lines) + "\r\n\n   \n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls[0], ["omarchy-menu-keybindings", "--print"])
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1][:4], ["omarchy-shell", "shell", "summon", "io.github.peterholko.school-mode"])
        self.assertEqual(json.loads(calls[1][4]), {
            "mode": "select", "prompt": "Keybindings", "options": lines, "width": 800, "maxHeight": 500,
        })
        self.assertFalse(marker.exists())

    def test_each_open_reads_the_current_mode_bindings(self):
        for listing in ("SUPER + K → Keybindings", "SUPER + RETURN → Terminal"):
            result, calls = self.run_viewer(listing)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(calls[0], ["omarchy-menu-keybindings", "--print"])
            self.assertEqual(json.loads(calls[1][4])["options"], [listing])

    def test_failed_listing_reports_error_without_opening_an_empty_menu(self):
        result, calls = self.run_viewer("partial output", exit_code=1)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual([call[0] for call in calls], ["omarchy-menu-keybindings", "omarchy-notification-send"])

    def test_empty_listing_has_an_explanation(self):
        result, calls = self.run_viewer("\n  \n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(calls[1][4])["options"], ["No keybindings available."])
