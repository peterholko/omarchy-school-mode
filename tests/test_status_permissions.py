"""Verify public status permissions at the atomic publication boundary."""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "service"))
from omarchy_kids.core import paths, storage


class PublicStatusPermissions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.context = ExitStack()
        self.addCleanup(self.context.close)
        self.context.enter_context(patch.dict(os.environ, {"SCREEN_TIME_ROOT": str(self.root)}))
        self.context.enter_context(patch.object(paths, "PARENT_STATE_DIR", self.root / "status"))
        self.addCleanup(os.umask, os.umask(0o077))
        self.layout = paths.Layout("system", self.root / "config.json", self.root / "state", self.root / "sock")
        self.target = self.root / "status/linnea/school-mode/status.json"

    def publish(self, revision):
        storage.public_status(self.layout, "linnea", "school-mode", {
            "schemaVersion": 1, "enabled": True, "mode": "free", "revision": revision,
            "schoolApps": ["chromium", "io.github.peterholko.math"],
        })

    def test_first_and_replacement_status_are_readable_before_rename(self):
        replace = os.replace
        published = []

        def check_then_replace(source, destination):
            self.assertEqual(Path(destination), self.target)
            # A file watcher may open the new inode immediately after rename.
            self.assertEqual(stat.S_IMODE(Path(source).stat().st_mode), 0o644)
            if self.target.exists():
                self.assertEqual(stat.S_IMODE(self.target.stat().st_mode), 0o644)
                self.assertEqual(json.loads(self.target.read_text())["revision"], len(published))
            replace(source, destination)
            published.append(json.loads(self.target.read_text())["revision"])
            self.assertEqual(stat.S_IMODE(self.target.stat().st_mode), 0o644)

        with patch.object(os, "replace", side_effect=check_then_replace):
            self.publish(1)
            self.publish(2)
        self.assertEqual(published, [1, 2])

    def test_public_directories_are_traversable_under_service_umask(self):
        self.publish(1)
        for directory in (self.root / "status", self.target.parent.parent, self.target.parent):
            self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o755)

    def test_parent_settings_stay_private_at_the_same_boundary(self):
        target = self.root / "private/password.json"
        replace = os.replace

        def check_then_replace(source, destination):
            self.assertEqual(stat.S_IMODE(Path(source).stat().st_mode), 0o600)
            replace(source, destination)
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)

        with patch.object(os, "replace", side_effect=check_then_replace):
            storage.write_json(target, {"password_hash": "test-only"})
            storage.write_json(target, {"password_hash": "replacement-test-only"})

    def test_failed_publication_keeps_previous_readable_status(self):
        self.publish(1)
        previous = self.target.read_bytes()
        with patch.object(os, "replace", side_effect=OSError("simulated rename failure")):
            with self.assertRaises(OSError):
                self.publish(2)
        self.assertEqual(self.target.read_bytes(), previous)
        self.assertEqual(stat.S_IMODE(self.target.stat().st_mode), 0o644)
        self.assertEqual(list(self.target.parent.iterdir()), [self.target])


if __name__ == "__main__":
    unittest.main()
