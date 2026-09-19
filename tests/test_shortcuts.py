"""Run the actual shortcut script with recorded compositor calls."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
BASH = shutil.which("bash")


@unittest.skipUnless(BASH and shutil.which("jq"), "Bash and jq are required")
class ShortcutTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.bin = self.base / "bin"
        self.bin.mkdir()
        self.log = self.base / "calls.jsonl"
        hyprctl = self.bin / "hyprctl"
        hyprctl.write_text(f"#!{sys.executable}\n" + '''import json, os, sys
with open(os.environ['COMPOSITOR_LOG'], 'a') as stream:
    stream.write(json.dumps(sys.argv[1:]) + '\\n')
if sys.argv[1] == 'eval' and os.environ.get('FAIL_EVAL') == '1':
    sys.exit(1)
print('ok')
''')
        hyprctl.chmod(0o755)
        if not shutil.which("flock"):
            # macOS lacks util-linux flock; lock the inherited descriptor with
            # the same syscall. The parent shell keeps that description open.
            lock = self.bin / "flock"
            lock.write_text(f"#!{sys.executable}\nimport fcntl, sys\nfcntl.flock(int(sys.argv[1]), fcntl.LOCK_EX)\n")
            lock.chmod(0o755)
        self.env = {**os.environ, "PATH": str(self.bin) + os.pathsep + os.environ["PATH"],
                    "XDG_RUNTIME_DIR": str(self.base / "runtime"), "COMPOSITOR_LOG": str(self.log)}
        self.marker = Path(self.env["XDG_RUNTIME_DIR"]) / "omarchy-community-school-mode/shortcut-policy.active"

    def run_policy(self, *args, success=True):
        result = subprocess.run([BASH, str(ROOT / "shortcut-policy"), *args], env=self.env,
                                text=True, capture_output=True, timeout=10)
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)
        return result

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def test_free_time_routes_only_approved_shortcuts_and_keeps_parent_terminal(self):
        self.run_policy("enter", "free")
        script = next(call[1] for call in self.calls() if call[0] == "eval")
        self.assertNotIn('hl.unbind("SUPER + RETURN")', script)
        for key in ("SUPER + SHIFT + A", "SUPER + SHIFT + Y", "SUPER + SHIFT + D", "SUPER + SHIFT + X"):
            self.assertIn(f'hl.unbind("{key}")', script)
            self.assertNotIn(f'hl.bind("{key}"', script)
        for line in script.splitlines():
            if line.startswith("hl.bind("):
                self.assertIn("io.github.peterholko.school-mode", line)
        ids = re.findall(r'"desktopId":"([^"]+)"', script)
        self.assertEqual(set(ids), {"chromium", "org.gnome.Nautilus", "omawrite", "obsidian",
                                    "cliamp", "Google Maps", "Khan Academy", "Wikipedia"})
        self.assertIn("mode=free", self.marker.read_text())

    def test_switching_modes_reloads_previous_layer_and_exit_restores_bindings(self):
        self.run_policy("enter", "free")
        self.run_policy("enter", "school")
        scripts = [call[1] for call in self.calls() if call[0] == "eval"]
        self.assertIn('hl.unbind("SUPER + RETURN")', scripts[-1])
        self.assertNotIn("launchAllowedApp", scripts[-1])
        self.assertIn("mode=school", self.marker.read_text())
        self.run_policy("exit")
        self.assertEqual(sum(call[0] == "reload" for call in self.calls()), 2)
        self.assertFalse(self.marker.exists())

    def test_capture_shortcuts_open_filtered_menu_and_stop_before_starting(self):
        capture_log = self.base / "capture.jsonl"
        self.env["CAPTURE_LOG"] = str(capture_log)
        for name in ("omarchy-capture-screenrecording", "omarchy-shell"):
            executable = self.bin / name
            executable.write_text(f"#!{sys.executable}\n" + '''import json, os, sys
from pathlib import Path
name = Path(sys.argv[0]).name
with open(os.environ['CAPTURE_LOG'], 'a') as stream:
    stream.write(json.dumps([name, *sys.argv[1:]]) + '\\n')
sys.exit(int(os.environ.get('CAPTURE_STOP_RC', '1')) if name == 'omarchy-capture-screenrecording' else 0)
''')
            executable.chmod(0o755)
        plugin = "io.github.peterholko.school-mode"
        for mode in ("school", "free"):
            self.run_policy("enter", mode)
            script = [call[1] for call in self.calls() if call[0] == "eval"][-1]

            def run_binding(key, stop_code=1):
                pattern = r'hl\.bind\("' + re.escape(key) + r'", hl\.dsp\.exec_cmd\(\[\[(.*?)\]\]\)'
                match = re.search(pattern, script)
                self.assertIsNotNone(match, key)
                capture_log.unlink(missing_ok=True)
                result = subprocess.run([BASH, "-c", match.group(1)],
                                        env={**self.env, "CAPTURE_STOP_RC": str(stop_code)},
                                        text=True, capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                return [json.loads(line) for line in capture_log.read_text().splitlines()]

            self.assertEqual(run_binding("SUPER + CTRL + C"), [[
                "omarchy-shell", "shell", "toggle", plugin, '{"menu":"trigger.capture"}']])
            self.assertEqual(run_binding("ALT + PRINT"), [
                ["omarchy-capture-screenrecording", "--stop-recording"],
                ["omarchy-shell", "shell", "toggle", plugin, '{"menu":"trigger.capture.screenrecord"}']])
            self.assertEqual(run_binding("ALT + PRINT", stop_code=0), [
                ["omarchy-capture-screenrecording", "--stop-recording"]])

    def test_failed_application_clears_marker_for_retry(self):
        self.env["FAIL_EVAL"] = "1"
        self.run_policy("enter", "free", success=False)
        self.assertFalse(self.marker.exists())
        self.assertEqual(self.calls()[-1][0], "reload")

    def test_rejects_unknown_mode_before_compositor_calls(self):
        self.run_policy("enter", "parent", success=False)
        self.assertFalse(self.log.exists())


if __name__ == "__main__":
    unittest.main()
