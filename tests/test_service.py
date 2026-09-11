"""Load and destroy the real QML service; record rather than execute its IPC."""
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


class ServiceTest(unittest.TestCase):
    def setUp(self):
        self.engine = QQmlEngine()
        self.engine.addImportPath(str(ROOT / "tests/qml"))
        self.component = QQmlComponent(self.engine, QUrl.fromLocalFile(str(ROOT / "tests/fixtures/ServiceProbe.qml")))
        self.assertEqual(self.component.status(), QQmlComponent.Ready, str(self.component.errors()))
        self.probe = self.component.createWithInitialProperties({"pluginPath": str(ROOT)})
        self.assertIsNotNone(self.probe)
        self.addCleanup(self.engine.deleteLater)
        self.addCleanup(self.probe.deleteLater)
        QTest.qWait(30)

    def invoke(self, action):
        result = QMetaObject.invokeMethod(self.probe, "invoke", Q_RETURN_ARG(str), Q_ARG(str, action))
        QTest.qWait(20)
        return json.loads(result)

    def test_shutdown_and_restart_never_release_desktop_restrictions(self):
        self.assertTrue(self.invoke("school")["school"])
        self.invoke("stop")
        commands = self.invoke("inspect")["commands"]
        self.assertTrue(commands)
        self.assertTrue(all(command[-1] == "sync" for command in commands), commands)
        self.invoke("start")
        state = self.invoke("school")
        self.assertTrue(state["school"])
        self.assertGreater(len(state["commands"]), len(commands))

    def test_mode_arrival_synchronizes_without_waiting_for_poll_timer(self):
        count = len(self.invoke("inspect")["commands"])
        state = self.invoke("school")
        self.assertEqual(len(state["commands"]), count + 1)
        self.assertEqual(state["commands"][-1][-1], "sync")
        state = self.invoke("free")
        self.assertEqual(len(state["commands"]), count + 2)
        state = self.invoke("disabled")
        self.assertEqual(len(state["commands"]), count + 3)

    def test_invalid_status_is_not_treated_as_disabled_enrollment(self):
        self.assertTrue(self.invoke("school")["school"])
        state = self.invoke("invalid")
        self.assertFalse(state["connected"])
        self.assertTrue(state["school"])
        self.assertTrue(self.invoke("school")["connected"])


if __name__ == "__main__":
    unittest.main()
