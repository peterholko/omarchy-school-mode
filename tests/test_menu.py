"""Run the real plugin in Qt without executing desktop commands.

Requires PySide6: python -m unittest discover -s tests -v
The native menu/library fixtures model Omarchy's provider and app-change API.
"""
import json
import os
from pathlib import Path
import unittest

from PySide6.QtCore import Q_ARG, Q_RETURN_ARG, QMetaObject, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtTest import QTest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
APP = QGuiApplication.instance() or QGuiApplication([])


class MenuTest(unittest.TestCase):
    def load(self, expose_library, *, inject_service=False, lookup_available=True):
        self.engine = QQmlEngine()
        self.engine.addImportPath(str(ROOT / "tests/qml"))
        self.component = QQmlComponent(self.engine, QUrl.fromLocalFile(str(ROOT / "tests/fixtures/Probe.qml")))
        self.assertEqual(self.component.status(), QQmlComponent.Ready, str(self.component.errors()))
        self.probe = self.component.createWithInitialProperties({
            "exposeLibrary": expose_library,
            "injectService": inject_service,
            "lookupStartsAvailable": lookup_available,
            "installedPath": str(ROOT / "tests/fixtures"),
            "pluginPath": str(ROOT),
        })
        self.assertIsNotNone(self.probe)
        def dispose(probe=self.probe, engine=self.engine, component=self.component):
            probe.deleteLater()
            engine.deleteLater()
        self.addCleanup(dispose)
        QTest.qWait(20)
        return self.invoke("open")

    def invoke(self, action):
        raw = QMetaObject.invokeMethod(self.probe, "invoke", Q_RETURN_ARG(str), Q_ARG(str, action))
        QTest.qWait(1)
        return json.loads(raw)

    def test_approved_apps_with_and_without_host_library(self):
        for exposed in (True, False):
            with self.subTest(exposed=exposed):
                state = self.load(exposed)
                self.assertEqual(state["ids"], ["chromium", "org.gnome.Nautilus", "Khan Academy"])
                self.assertEqual(state["names"], ["Chromium", "Files", "Khan Academy"])
                self.assertEqual(state["icons"], ["image://icon/chromium", "image://icon/files", "image://icon/khan"])
                self.assertEqual(state["usesSharedLibrary"], exposed)
                self.assertEqual(json.loads(state["payload"])["menu"], "apps")
                self.assertTrue(state["menuPath"].endswith("/school-menu.jsonc"))

    def test_live_whitelist_and_revoked_launch(self):
        for exposed in (True, False):
            with self.subTest(exposed=exposed):
                self.load(exposed)
                state = self.invoke("revoke")
                self.assertEqual(state["ids"], ["Khan Academy"])
                self.assertEqual(state["launches"], [])
                self.assertEqual(self.invoke("launch")["launches"], ["Khan Academy"])
                self.assertEqual(self.invoke("empty")["ids"], [])

    def test_app_install_and_removal_refresh_open_menu(self):
        for exposed in (True, False):
            with self.subTest(exposed=exposed):
                self.load(exposed)
                self.assertEqual(self.invoke("remove-app")["ids"], ["chromium", "Khan Academy"])
                self.assertEqual(self.invoke("add-app")["ids"], ["chromium", "Khan Academy", "omawrite"])

    def test_free_time_and_return_to_school(self):
        for exposed in (True, False):
            with self.subTest(exposed=exposed):
                self.load(exposed)
                state = self.invoke("free")
                self.assertEqual(state["ids"], ["chromium", "org.gnome.Nautilus", "Khan Academy",
                    "com.github.PintaProject.Pinta", "cliamp", "io.github.peterholko.pawberry",
                    "io.github.peterholko.number-grove", "io.github.peterholko.paw-post"])
                self.assertTrue(state["menuPath"].endswith("/free-time-menu.jsonc"))
                self.assertEqual(self.invoke("remove-free")["removals"], [])
                self.assertEqual(self.invoke("school")["ids"], ["chromium", "org.gnome.Nautilus", "Khan Academy"])
                self.assertEqual(self.invoke("search")["ids"], ["org.gnome.Nautilus"])

    def test_free_time_rejects_unapproved_launches_and_stock_menu_routes(self):
        self.load(False)
        self.invoke("free")
        self.assertEqual(self.invoke("launch-discord")["launches"], [])
        self.assertEqual(self.invoke("discord-shortcut")["verdict"], "blocked")
        self.assertEqual(self.invoke("pinta-shortcut")["verdict"], "ok")
        self.assertEqual(self.invoke("inspect")["launches"], ["com.github.PintaProject.Pinta"])
        self.assertEqual(json.loads(self.invoke("community-route")["payload"])["menu"], "apps")
        self.invoke("school")
        self.assertEqual(self.invoke("pinta-shortcut")["verdict"], "blocked")

    def test_missing_status_does_not_expose_all_apps(self):
        self.load(True)
        self.invoke("free")
        self.assertEqual(self.invoke("disconnect")["ids"], [])
        self.invoke("loading")
        self.assertEqual(self.invoke("inspect")["ids"], [])

    def test_capture_deep_links_preserve_approved_apps_in_both_modes(self):
        self.load(True)
        for mode in ("school", "free"):
            self.invoke(mode)
            expected_ids = self.invoke("inspect")["ids"]
            for filename in ("school-menu.jsonc", "free-time-menu.jsonc"):
                entries = json.loads((ROOT / filename).read_text())
                for route in entries:
                    if not route.startswith("trigger.capture"):
                        continue
                    for prefix, field in (("route:", "menu"), ("initial-route:", "initialMenu")):
                        state = self.invoke(prefix + route)
                        self.assertEqual(json.loads(state["payload"])[field], route)
                        self.assertEqual(state["ids"], expected_ids)
                        self.assertNotIn("Discord", state["ids"])
                        self.assertTrue(state["menuPath"].endswith(f"/{mode if mode == 'school' else 'free-time'}-menu.jsonc"))
            for route in ("setup", "trigger", "trigger.capture-unrestricted", "install", "learn.community"):
                state = self.invoke("route:" + route)
                self.assertEqual(json.loads(state["payload"])["menu"], "apps")
            self.assertEqual(json.loads(self.invoke("route:style.theme")["payload"])["menu"], "style.theme")
        self.invoke("disconnect")
        state = self.invoke("route:trigger.capture.screenrecord")
        self.assertEqual(json.loads(state["payload"])["menu"], "trigger.capture.screenrecord")
        self.assertEqual(state["ids"], [])

    def test_capture_menu_is_curated_and_has_no_unrestricted_provider(self):
        captures = []
        for filename in ("school-menu.jsonc", "free-time-menu.jsonc"):
            entries = json.loads((ROOT / filename).read_text())
            self.assertEqual([item["provider"] for item in entries.values() if "provider" in item], ["apps"])
            self.assertEqual(entries["trigger.capture"]["parent"], "apps")
            self.assertTrue(all(key == "apps" or key == "style" or key.startswith("style.")
                                or key == "trigger.capture" or key.startswith("trigger.capture.") for key in entries))
            capture = {key: item for key, item in entries.items() if key.startswith("trigger.capture")}
            self.assertIn("pgrep", capture["trigger.capture.screenrecord.stop"]["when"])
            self.assertEqual(capture["trigger.capture.screenrecord.webcam"]["when"], "omarchy-hw-webcam")
            self.assertTrue(all("omarchy.menu" not in item.get("action", "") for item in capture.values()))
            captures.append(capture)
        self.assertEqual(captures[0], captures[1])

    def test_confirmed_disabled_enrollment_restores_normal_launcher(self):
        self.load(True)
        self.invoke("free")
        self.assertIn("Discord", self.invoke("disabled")["ids"])
        self.assertEqual(self.invoke("remove-free")["removals"], ["steam"])

    def test_private_browser_and_current_directory_variants_require_approval(self):
        self.load(False)
        self.invoke("free")
        state = self.invoke("private-shortcut")
        self.assertEqual(state["verdict"], "ok")
        self.assertEqual(state["commands"], [["uwsm-app", "--", "chromium", "--incognito"]])
        state = self.invoke("cwd-shortcut")
        self.assertEqual(state["commands"][-1], ["omarchy-launch-nautilus-cwd"])
        self.assertEqual(self.invoke("invalid-variant")["verdict"], "invalid")
        self.invoke("school")
        self.invoke("empty")
        self.assertEqual(self.invoke("private-shortcut")["verdict"], "blocked")
        self.assertEqual(self.invoke("cwd-shortcut")["verdict"], "blocked")

    def test_host_library_becomes_available_after_open(self):
        self.load(False)
        self.invoke("supply-library")
        state = self.invoke("inspect")
        self.assertTrue(state["usesSharedLibrary"])
        self.assertEqual(state["ids"], ["chromium", "org.gnome.Nautilus", "Khan Academy"])

    def test_injected_service_works_when_host_lookup_is_unavailable(self):
        state = self.load(True, inject_service=True, lookup_available=False)
        self.assertEqual(state["ids"], ["chromium", "org.gnome.Nautilus", "Khan Academy"])
        diagnostic = self.invoke("diagnostics")
        self.assertEqual(diagnostic["serviceSource"], "injected")
        self.assertTrue(diagnostic["service"]["enabled"])
        self.assertFalse(diagnostic["freshLookup"]["available"])
        self.assertGreater(diagnostic["availableApps"], diagnostic["visibleApps"])
        self.assertEqual(diagnostic["visibleApps"], 3)
        self.assertNotIn("Discord", self.invoke("free")["ids"])
        self.assertEqual(self.invoke("disconnect")["ids"], [])

    def test_open_and_refresh_recover_a_service_published_without_notification(self):
        for action in ("open", "refresh"):
            with self.subTest(action=action):
                self.assertEqual(self.load(True, lookup_available=False)["ids"], [])
                self.assertEqual(self.invoke("publish-service")["ids"], [])
                # Diagnostics expose the disagreement without fixing it.
                diagnostic = self.invoke("diagnostics")
                self.assertFalse(diagnostic["service"]["available"])
                self.assertTrue(diagnostic["freshLookup"]["available"])
                self.assertEqual(self.invoke(action)["ids"], ["chromium", "org.gnome.Nautilus", "Khan Academy"])

    def test_missing_service_recovers_while_menu_stays_open(self):
        self.assertEqual(self.load(True, lookup_available=False)["ids"], [])
        self.invoke("publish-service")
        QTest.qWait(1100)
        self.assertEqual(self.invoke("inspect")["ids"], ["chromium", "org.gnome.Nautilus", "Khan Academy"])
        self.invoke("revoke")
        self.assertEqual(self.invoke("inspect")["ids"], ["Khan Academy"])


if __name__ == "__main__":
    unittest.main()
