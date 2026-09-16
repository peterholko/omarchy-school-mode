"""Render Omarchy's real lock view in an ordinary test window, never a lock.

The FileView adapter reads a temporary JSON file; Quickshell process calls are
inert. This checks display and password-field behavior, not Linux PAM or the
Wayland session-lock protocol. Inspect the resulting screenshots as well.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QObject, QPointF, QUrl, Slot, Qt
from PySide6.QtGui import QGuiApplication, QFontDatabase
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickItem, QQuickWindow
from PySide6.QtTest import QTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'service'))
from omarchy_kids.school_mode import lock_notice_setup

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--omarchy', required=True, type=Path)
parser.add_argument('--output', required=True, type=Path)
args = parser.parse_args()
base = args.output.resolve()
imports = base / 'qml'
shutil.copytree(ROOT / 'tests/qml', imports, dirs_exist_ok=True)
for folder in ('Quickshell', 'qs'):
    shutil.copytree(ROOT / 'tests/visual-fixtures' / folder, imports / folder, dirs_exist_ok=True)
ui = imports / 'qs/Ui'
names = ['BackgroundMedia', 'BorderSurface', 'BorderOverlay']
for name in names:
    shutil.copyfile(args.omarchy / 'shell/Ui' / (name + '.qml'), ui / (name + '.qml'))
(ui / 'qmldir').write_text('module qs.Ui\n' + ''.join(f'{name} 1.0 {name}.qml\n' for name in names))
commons = imports / 'qs/Commons'
for name in ['Style.qml', 'Border.qml', 'Util.qml', 'BorderGeometry.js']:
    shutil.copyfile(args.omarchy / 'shell/Commons' / name, commons / name)
(commons / 'qmldir').write_text('module qs.Commons\n' + ''.join(
    f'singleton {name} 1.0 {name}.qml\n' for name in ['Style', 'Border', 'Util', 'Color']))
color = commons / 'Color.qml'
color.write_text(color.read_text().replace('  property var shellValues:', '''  property var lock: ({
    background: background, text: foreground, placeholder: foreground,
    textError: urgent, borderActive: accent, borderError: urgent, selection: accent
  })
  property var shellValues:'''))
(imports / 'Quickshell/Io/FileView.qml').write_text('''import QtQuick
QtObject {
  property string path: ""
  property bool watchChanges: false
  property bool printErrors: false
  property string contents: ""
  signal fileChanged()
  signal loaded()
  signal loadFailed()
  function text() { return contents }
  function reload() {
    if (!fixtureFs.exists(path)) { loadFailed(); return }
    contents = fixtureFs.read(path)
    loaded()
  }
  onPathChanged: Qt.callLater(reload)
  Component.onCompleted: Qt.callLater(reload)
}
''')
native = (args.omarchy / lock_notice_setup.RELATIVE_VIEW).read_text()
(base / 'LockView.qml').write_text(lock_notice_setup.add_notice(native,
    lock_notice_setup.snippet(ROOT / 'service/lock-notice/LockNotice.qml')))
(base / 'Probe.qml').write_text('''import QtQuick
import QtQuick.Window
import qs.Commons
Window {
  id: root
  width: 960
  height: 640
  visible: true
  property string submitted: ""
  LockView {
    id: lock
    objectName: "lockView"
    anchors.fill: parent
    onPasswordTextEdited: function(password) { passwordText = password }
    onSubmitPassword: function(password) { root.submitted = password }
  }
  function dark() { Color.background = "#222431"; Color.foreground = "#eee9ef" }
  function large() { Style.fontBaseSize = 20 }
}
''')

status_path = base / 'status.json'
status = {'schemaVersion': 1, 'enabled': True, 'mode': 'free',
          'freeTimeTimerVersion': 1, 'freeTimeReady': True, 'freeTimeExpired': False}


def publish(value):
    # Atomic replacement models the service publisher; the real component's
    # two-second timer must discover each change without reopening the view.
    temporary = base / 'status.new'
    temporary.write_text(json.dumps(value))
    temporary.replace(status_path)


class Files(QObject):
    @Slot(str, result=bool)
    def exists(self, path):
        return path.endswith('/school-mode/status.json') and status_path.is_file()

    @Slot(str, result=str)
    def read(self, path):
        return status_path.read_text() if self.exists(path) else ''


publish(status)
app = QGuiApplication.instance() or QGuiApplication([])
QFontDatabase.addApplicationFont(str(args.omarchy / 'default/fonts/omarchy/omarchy.ttf'))
engine = QQmlEngine()
engine.addImportPath(str(imports))
files = Files()
engine.rootContext().setContextProperty('fixtureFs', files)
warnings = []
engine.warnings.connect(lambda errors: warnings.extend(error.toString() for error in errors))
component = QQmlComponent(engine, QUrl.fromLocalFile(str(base / 'Probe.qml')))
assert not component.isError(), [e.toString() for e in component.errors()]
window = component.create()
assert isinstance(window, QQuickWindow)
window.show()
QTest.qWait(200)
view = window.findChild(QQuickItem, 'lockView')
notice = window.findChild(QQuickItem, 'schoolParentLockNotice')
assert notice is not None, warnings
assert not notice.isVisible(), 'Ordinary child locks must have no parent notice'
field = window.activeFocusItem()
assert field is not None


def screenshot(name):
    QTest.qWait(60)
    assert window.grabWindow().save(str(base / name))


def assert_layout():
    title = window.findChild(QQuickItem, 'parentUnlockTitle')
    explanation = window.findChild(QQuickItem, 'parentUnlockExplanation')
    assert notice.isVisible() and title.isVisible() and explanation.isVisible()
    position = notice.mapToScene(QPointF(0, 0))
    field_bottom = field.parentItem().mapToScene(QPointF(0, field.parentItem().height())).y()
    assert position.y() > field_bottom, (position.y(), field_bottom)
    assert position.x() >= 0 and position.x() + notice.width() <= window.width()
    assert position.y() + notice.height() <= window.height()
    assert explanation.height() >= explanation.property('implicitHeight')


screenshot('manual-lock.png')
# Exercise a live expiry while a password is partly typed. No field replacement
# or focus change is allowed when the notice becomes visible.
QTest.keyClick(window, Qt.Key_A)
status['freeTimeExpired'] = True
publish(status)
QTest.qWait(2150)
assert window.activeFocusItem() == field and field.property('text') == 'a'
assert field.property('displayText') != 'a'
assert_layout()
QTest.keyClick(window, Qt.Key_U, Qt.ControlModifier)
screenshot('expired-light.png')
QTest.keyClick(window, Qt.Key_P)
QTest.keyClick(window, Qt.Key_Return)
assert window.property('submitted') == 'p' and field.property('text') == ''

window.dark()
window.large()
window.setWidth(540)
window.setHeight(600)
QTest.qWait(60)
assert_layout()
screenshot('expired-dark-large-text.png')

for patch in [{'mode': 'school'}, {'enabled': False}, {'freeTimeReady': False},
              {'schemaVersion': 2}, {'freeTimeTimerVersion': 0}, {'freeTimeExpired': False}]:
    publish({**status, **patch})
    QTest.qWait(2100)
    assert not notice.isVisible(), patch
publish(status)
QTest.qWait(2100)
assert notice.isVisible()
status_path.write_text('{invalid json')
QTest.qWait(2100)
assert not notice.isVisible()
status_path.unlink()
QTest.qWait(2100)
assert not notice.isVisible()
view.setProperty('inputEnabled', False)
view.setProperty('loadBackground', False)
publish(status)
QTest.qWait(2100)
assert not any(item.isVisible() for item in window.findChildren(QQuickItem, 'schoolParentLockNotice'))
view.setProperty('inputEnabled', True)
view.setProperty('loadBackground', True)
QTest.qWait(150)
notice = window.findChild(QQuickItem, 'schoolParentLockNotice')
assert notice is not None and notice.isVisible(), 'An already expired lock must show the notice on opening'
assert_layout()
assert not warnings, warnings
window.close()
print(f'PASS: native lock layout, live expiry, masked input/focus/submit, light/dark, large text, status transitions and inactive preview. Inspect {base}.')
