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
    def load(self, expose_library):
        self.engine = QQmlEngine()
        self.engine.addImportPath(str(ROOT / "tests/qml"))
        self.component = QQmlComponent(self.engine, QUrl.fromLocalFile(str(ROOT / "tests/fixtures/Probe.qml")))
        self.assertEqual(self.component.status(), QQmlComponent.Ready, str(self.component.errors()))
        self.probe = self.component.createWithInitialProperties({
            "exposeLibrary": expose_library,
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
                self.assertIn("steam", self.invoke("free")["ids"])
                self.assertEqual(self.invoke("remove-free")["removals"], ["steam"])
                self.assertNotIn("steam", self.invoke("school")["ids"])
                self.assertEqual(self.invoke("search")["ids"], ["org.gnome.Nautilus"])

    def test_host_library_becomes_available_after_open(self):
        self.load(False)
        self.invoke("supply-library")
        state = self.invoke("inspect")
        self.assertTrue(state["usesSharedLibrary"])
        self.assertEqual(state["ids"], ["chromium", "org.gnome.Nautilus", "Khan Academy"])


if __name__ == "__main__":
    unittest.main()
