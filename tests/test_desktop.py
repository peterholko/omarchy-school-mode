"""Exercise desktop transitions against temporary files and recorded IPC."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


class DesktopTest(unittest.TestCase):
    PAYLOAD = ROOT  # The plugin's own copy, run by Service.qml and the README commands.

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        spec = importlib.util.spec_from_file_location("school_desktop_test", self.PAYLOAD / "school-desktop.py")
        self.desktop = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.desktop)
        self.desktop.STATE = self.base / "state"
        self.desktop.CONFIG = self.base / "config/shell.json"
        self.desktop.JOURNAL = self.desktop.STATE / "desktop.json"
        self.desktop.CONSENT = self.desktop.STATE / "consent.json"
        self.desktop.SOURCE = self.base / "payload"
        self.desktop.SOURCE.mkdir()
        (self.desktop.SOURCE / "shortcut-policy").write_bytes((self.PAYLOAD / "shortcut-policy").read_bytes())
        self.runtime = self.base / "runtime"
        self.marker = self.runtime / "omarchy-community-school-mode/shortcut-policy.active"
        self.original = {"version": 1, "disabledPlugins": ["unrelated.disabled"],
                         "bar": {"layout": {"right": ["my.clock"]}}}
        self.desktop.write(self.desktop.CONFIG, self.original)
        self.desktop.write(self.desktop.CONSENT, {"enabled": True})
        self.status = {"schemaVersion": 1, "enabled": True, "mode": "free"}
        self.calls = []
        self.dnd = "off"
        self.failure = None
        self.live_shortcuts = False
        original_read = self.desktop.read

        def read(path, default=None):
            if str(path).startswith("/var/lib/omarchy-kids-controls/status/"):
                return copy.deepcopy(self.status)
            return original_read(path, default)

        self.addCleanup(patch.stopall)
        patch.object(self.desktop, "read", side_effect=read).start()
        patch.object(self.desktop, "command", side_effect=self.command).start()
        patch.dict(os.environ, {"XDG_RUNTIME_DIR": str(self.runtime),
                               "HYPRLAND_INSTANCE_SIGNATURE": "session-one"}).start()

    def command(self, *args):
        self.calls.append(args)
        if self.failure and self.failure(args):
            raise ValueError("simulated desktop command failure")
        if args == ("hyprctl", "binds"):
            return ("bind\n\tdescription: School / Free Time: Menu\n"
                    "bind\n\tdescription: School / Free Time: Apps\n") if self.live_shortcuts else "bind\n\tdescription: Omarchy menu\n"
        if args[:2] == ("omarchy-shell", "notifications"):
            if args[2] == "dndState":
                return self.dnd
            self.dnd = args[3]
        if len(args) > 2 and Path(args[1]).name == "shortcut-policy":
            if args[2] == "enter":
                self.live_shortcuts = True
                self.marker.parent.mkdir(parents=True, exist_ok=True)
                self.marker.write_text(f"version=2\nmode={args[3]}\n")
            else:
                self.live_shortcuts = False
                self.marker.unlink(missing_ok=True)
        return "ok"

    def calls_for(self, helper, action=None):
        return [args for args in self.calls if len(args) > 2 and Path(args[1]).name == helper
                and (action is None or args[2] == action)]

    def launcher_disabled(self):
        return "omarchy.menu" in self.desktop.read(self.desktop.CONFIG)["disabledPlugins"]

    def test_free_time_keeps_approved_launcher_without_school_effects(self):
        self.desktop.synchronize()
        self.assertTrue(self.launcher_disabled())
        self.assertEqual(self.calls_for("window-session"), [])
        self.assertEqual(self.dnd, "off")
        self.assertEqual(len(self.calls_for("shortcut-policy", "enter")), 1)
        self.assertEqual(self.calls_for("shortcut-policy", "enter")[0][-1], "free")
        self.desktop.synchronize()
        self.assertEqual(len(self.calls_for("shortcut-policy", "enter")), 1)
        self.assertEqual(self.desktop.read(self.desktop.CONFIG)["bar"], self.original["bar"])

    def test_school_round_trip_restores_windows_and_current_notification_preference(self):
        self.desktop.synchronize()
        self.dnd = "on"  # A preference changed during Free Time is retained.
        self.status["mode"] = "school"
        self.desktop.synchronize()
        self.assertTrue(self.launcher_disabled())
        self.assertEqual(len(self.calls_for("window-session", "enter")), 1)
        self.status["mode"] = "free"
        self.desktop.synchronize()
        self.assertTrue(self.launcher_disabled())
        self.assertEqual(len(self.calls_for("window-session", "exit")), 1)
        self.assertEqual(self.dnd, "on")
        self.assertEqual([args[-1] for args in self.calls_for("shortcut-policy", "enter")], ["free", "school", "free"])

    def test_disable_restores_desktop_without_reverting_free_time_notification_changes(self):
        self.status["mode"] = "school"
        self.desktop.synchronize()
        self.status["mode"] = "free"
        self.desktop.synchronize()
        self.assertEqual(self.dnd, "off")
        self.dnd = "on"
        self.status["enabled"] = False
        self.desktop.synchronize()
        self.assertEqual(self.desktop.read(self.desktop.CONFIG), self.original)
        self.assertFalse(self.desktop.JOURNAL.exists())
        self.assertFalse(self.marker.exists())
        self.assertEqual(self.dnd, "on")

    def test_preexisting_disabled_menu_is_preserved_on_removal(self):
        self.original["disabledPlugins"].append("omarchy.menu")
        self.desktop.write(self.desktop.CONFIG, self.original)
        self.desktop.synchronize()
        self.desktop.write(self.desktop.CONSENT, {"enabled": False})
        self.desktop.synchronize()
        self.assertEqual(self.desktop.read(self.desktop.CONFIG), self.original)

    def test_v1_upgrade_keeps_original_recovery_values(self):
        config = copy.deepcopy(self.original)
        config["disabledPlugins"].append("omarchy.menu")
        self.desktop.write(self.desktop.CONFIG, config)
        self.desktop.write(self.desktop.JOURNAL, {"version": 1, "menuWasDisabled": False,
            "dnd": "off", "effectsApplied": True, "instance": "session-one"})
        self.dnd = "on"
        self.desktop.synchronize()
        journal = self.desktop.read(self.desktop.JOURNAL)
        self.assertEqual(journal["version"], 2)
        self.assertFalse(journal["menuWasDisabled"])
        self.assertFalse(journal["schoolActive"])
        self.assertTrue(self.launcher_disabled())
        self.assertEqual(self.dnd, "off")
        self.status["enabled"] = False
        self.desktop.synchronize()
        self.assertEqual(self.desktop.read(self.desktop.CONFIG), self.original)

    def test_missing_or_invalid_status_retains_restrictions(self):
        self.desktop.synchronize()
        for status in (None, [], {}, {"schemaVersion": 1, "enabled": True, "mode": "broken"}):
            with self.subTest(status=status):
                self.status = status
                before = len(self.calls)
                with self.assertRaises(ValueError):
                    self.desktop.synchronize()
                self.assertTrue(self.launcher_disabled())
                self.assertTrue(self.desktop.JOURNAL.exists())
                self.assertFalse(any(args[:2] == ("omarchy-shell", "notifications")
                    or (len(args) > 2 and Path(args[1]).name == "window-session") for args in self.calls[before:]))
                self.assertEqual(self.desktop.read(self.desktop.JOURNAL)["appliedMode"], "school")

    def test_failed_transition_keeps_recovery_and_retries(self):
        self.status["mode"] = "school"
        self.desktop.synchronize()
        self.status["mode"] = "free"
        self.failure = lambda args: len(args) > 3 and Path(args[1]).name == "shortcut-policy" and args[-1] == "free"
        with self.assertRaises(ValueError):
            self.desktop.synchronize()
        self.assertTrue(self.launcher_disabled())
        self.assertTrue(self.desktop.JOURNAL.exists())
        self.failure = None
        self.desktop.synchronize()
        self.assertEqual(self.desktop.read(self.desktop.JOURNAL)["appliedMode"], "free")

    def test_update_or_missing_runtime_marker_reapplies_shortcuts(self):
        self.desktop.synchronize()
        self.marker.unlink()
        self.desktop.synchronize()
        self.assertEqual(len(self.calls_for("shortcut-policy", "enter")), 2)
        with (self.desktop.SOURCE / "shortcut-policy").open("a") as stream:
            stream.write("\n# Updated plugin\n")
        self.desktop.synchronize()
        self.assertEqual(len(self.calls_for("shortcut-policy", "enter")), 3)
        os.environ["HYPRLAND_INSTANCE_SIGNATURE"] = "session-two"
        self.desktop.synchronize()
        self.assertEqual(len(self.calls_for("shortcut-policy", "enter")), 4)

    def test_returning_to_school_after_failed_free_time_restore_reapplies_school_effects(self):
        self.status["mode"] = "school"
        self.desktop.synchronize()
        self.status["mode"] = "free"
        self.failure = lambda args: args == ("omarchy-shell", "notifications", "setDnd", "off")
        with self.assertRaises(ValueError):
            self.desktop.synchronize()
        self.assertEqual(len(self.calls_for("window-session", "exit")), 1)
        self.failure = None
        self.status["mode"] = "school"
        self.desktop.synchronize()
        self.assertEqual(len(self.calls_for("window-session", "enter")), 2)
        self.assertEqual(self.dnd, "on")
        self.assertTrue(self.launcher_disabled())

    def test_reboot_reapplies_school_shortcuts_before_waiting_for_status(self):
        self.status["mode"] = "school"
        self.desktop.synchronize()
        self.marker.unlink()
        self.live_shortcuts = False
        os.environ["HYPRLAND_INSTANCE_SIGNATURE"] = "after-reboot"
        self.status = None
        with self.assertRaisesRegex(ValueError, "waiting"):
            self.desktop.synchronize()
        self.assertTrue(self.launcher_disabled())
        self.assertTrue(self.live_shortcuts)
        self.assertEqual(self.calls_for("shortcut-policy", "enter")[-1][-1], "school")

    def test_first_login_without_status_keeps_stock_launcher_unavailable(self):
        self.status = None
        with self.assertRaisesRegex(ValueError, "waiting"):
            self.desktop.synchronize()
        self.assertTrue(self.launcher_disabled())
        self.assertTrue(self.live_shortcuts)
        self.assertFalse(self.desktop.read(self.desktop.JOURNAL)["menuWasDisabled"])

    def test_reboot_restores_school_effects_and_original_parent_preferences(self):
        self.status["mode"] = "school"
        self.desktop.synchronize()
        self.marker.unlink()
        self.live_shortcuts = False
        self.dnd = "off"
        os.environ["HYPRLAND_INSTANCE_SIGNATURE"] = "new-login"
        self.desktop.synchronize()
        self.assertTrue(self.launcher_disabled())
        self.assertTrue(self.live_shortcuts)
        self.assertEqual(self.dnd, "on")
        self.assertEqual(len(self.calls_for("window-session", "enter")), 2)
        self.status["mode"] = "free"
        self.desktop.synchronize()
        self.assertTrue(self.launcher_disabled())
        self.assertEqual(self.dnd, "off")
        self.status["enabled"] = False
        self.desktop.synchronize()
        self.assertEqual(self.desktop.read(self.desktop.CONFIG), self.original)

    def test_delayed_status_recovers_into_free_time_without_school_window_effects(self):
        self.status = None
        with self.assertRaises(ValueError):
            self.desktop.synchronize()
        self.assertTrue(self.launcher_disabled())
        self.assertEqual(self.calls_for("window-session"), [])
        self.status = {"schemaVersion": 1, "enabled": True, "mode": "free"}
        self.desktop.synchronize()
        self.assertEqual(self.calls_for("shortcut-policy", "enter")[-1][-1], "free")
        self.assertTrue(self.launcher_disabled())
        self.assertEqual(self.calls_for("window-session"), [])
        self.assertEqual(self.dnd, "off")

    def test_compositor_reload_does_not_make_old_marker_authoritative(self):
        for mode in ("school", "free"):
            with self.subTest(mode=mode):
                self.status["mode"] = mode
                self.desktop.synchronize()
                self.assertTrue(self.marker.exists())
                self.live_shortcuts = False  # A late startup/config reload reset the bindings.
                before = len(self.calls_for("shortcut-policy", "enter"))
                self.desktop.synchronize()
                self.assertTrue(self.live_shortcuts)
                self.assertEqual(len(self.calls_for("shortcut-policy", "enter")), before + 1)

    def test_notification_startup_failure_does_not_block_app_restrictions(self):
        self.status["mode"] = "school"
        self.failure = lambda args: args[:2] == ("omarchy-shell", "notifications")
        with self.assertRaises(ValueError):
            self.desktop.synchronize()
        self.assertTrue(self.launcher_disabled())
        self.assertTrue(self.live_shortcuts)
        self.failure = None
        self.dnd = "on"  # Capture the real preference once notifications become available.
        self.desktop.synchronize()
        self.status["enabled"] = False
        self.desktop.synchronize()
        self.assertEqual(self.desktop.read(self.desktop.CONFIG), self.original)
        self.assertEqual(self.dnd, "on")

    def test_window_startup_failure_does_not_block_app_restrictions(self):
        self.status["mode"] = "school"
        self.failure = lambda args: len(args) > 2 and Path(args[1]).name == "window-session" and args[2] == "enter"
        with self.assertRaises(ValueError):
            self.desktop.synchronize()
        self.assertTrue(self.launcher_disabled())
        self.assertTrue(self.live_shortcuts)
        self.failure = None
        self.desktop.synchronize()
        self.assertEqual(self.dnd, "on")
        self.assertEqual(len(self.calls_for("window-session", "enter")), 2)


class InstalledDesktopTest(DesktopTest):
    """`omarchy-kids-controls disable|remove school` restores with the installed copy.

    It reads the journal the plugin's copy wrote, so both must behave alike.
    """
    PAYLOAD = ROOT / "service"

    def test_installed_helpers_match_the_plugin_copies(self):
        for name in ("school-desktop.py", "shortcut-policy", "window-session"):
            self.assertEqual((ROOT / "service" / name).read_bytes(), (ROOT / name).read_bytes(),
                             f"service/{name} is stale; run: cp {name} service/{name}")


if __name__ == "__main__":
    unittest.main()
