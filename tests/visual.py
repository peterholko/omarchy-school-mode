"""Render real plugin QML with Omarchy's real controls and portable host adapters.

Only Quickshell's process/IPC and window hosting are fixtures; no desktop command
executes. This does not validate Linux session locking or PAM authentication.
"""
import argparse
import json
import os
from pathlib import Path
import shutil

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_CONTROLS_STYLE', 'Basic')
from PySide6.QtCore import QUrl, QPointF, QMetaObject, Q_RETURN_ARG, Qt
from PySide6.QtGui import QGuiApplication, QFontDatabase
from PySide6.QtQml import QQmlEngine, QQmlComponent
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--omarchy', required=True, type=Path)
parser.add_argument('--output', required=True, type=Path)
args = parser.parse_args()
base = args.output.resolve()
imports = base / 'qml'
shutil.copytree(ROOT/'tests/qml', imports, dirs_exist_ok=True)
for folder in ('Quickshell', 'qs'):
    shutil.copytree(ROOT/'tests/visual-fixtures'/folder, imports/folder, dirs_exist_ok=True)
ui = imports/'qs/Ui'
names = 'Button TextField Toggle ToggleSwitch PanelSectionHeader PanelSeparator PanelActionButton PanelToolTip BorderSurface BorderOverlay BarWidget BarIconButton WidgetButton OpticalGlyph Panel PanelController PanelHero'.split()
for name in names:
    shutil.copyfile(args.omarchy/'shell/Ui'/f'{name}.qml', ui/f'{name}.qml')
(ui/'qmldir').write_text('module qs.Ui\n'+''.join(f'{name} 1.0 {name}.qml\n' for name in names+['KeyboardPanel']))
commons = imports/'qs/Commons'
for name in ['Style.qml', 'Border.qml', 'BorderGeometry.js', 'Util.qml']:
    shutil.copyfile(args.omarchy/'shell/Commons'/name, commons/name)
(commons/'qmldir').write_text('module qs.Commons\n'+''.join(f'singleton {name} 1.0 {name}.qml\n' for name in ['Style','Border','Color','Util']))
(imports/'Quickshell/qmldir').write_text('module Quickshell\nsingleton Quickshell 1.0 Quickshell.qml\nsingleton DesktopEntries 1.0 DesktopEntries.qml\nFloatingWindow 1.0 FloatingWindow.qml\n')
with (imports/'Quickshell/Io/qmldir').open('a') as handle:
    handle.write('\nIpcHandler 1.0 IpcHandler.qml\n')
for name in ('Probe.qml', 'BarProbe.qml'):
    (base/name).write_text((ROOT/'tests/visual-fixtures'/name).read_text().replace('@PLUGIN_URL@', ROOT.as_uri()))

app = QGuiApplication.instance() or QGuiApplication([])
QFontDatabase.addApplicationFont(str(args.omarchy/'default/fonts/omarchy/omarchy.ttf'))
engine = QQmlEngine()
engine.addImportPath(str(imports))
components = []


def load(name):
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(base/name)))
    assert not component.isError(), [error.toString() for error in component.errors()]
    components.append(component)
    instance = component.create()
    assert instance is not None
    QTest.qWait(200)
    return instance


probe = load('Probe.qml')
win = next(w for w in app.allWindows() if w.objectName() == 'settingsWindow')


def state():
    return json.loads(QMetaObject.invokeMethod(probe, 'inspect', Q_RETURN_ARG(str)))


def find(name):
    item = probe.findChild(QQuickItem, name)
    if item is None:
        item = win.contentItem().findChild(QQuickItem, name)
    assert item is not None, name
    return item


def click(name):
    item = find(name)
    point = item.mapToScene(QPointF(item.width()/2, item.height()/2)).toPoint()
    QTest.mouseClick(win, Qt.LeftButton, Qt.NoModifier, point)
    QTest.qWait(40)


def screenshot(window, name):
    QTest.qWait(80)
    assert window.grabWindow().save(str(base/name))


screenshot(win, 'school.png')
click('freeTimeTab')
assert state()['page'] == 'free', state()
screenshot(win, 'free-time.png')
field = find('freeTimeMinutesField')
field.forceActiveFocus()
QMetaObject.invokeMethod(field, 'selectAll')
QTest.keyClick(win, Qt.Key_4)
QTest.keyClick(win, Qt.Key_5)
click('saveFreeTimeButton')
assert any(command[-1] == '{"free_time_minutes":45}' for command in state()['commands']), state()
assert state()['writes'] == ['fixture-parent-secret\n'], state()
assert state()['note'] == 'Saved.', state()
screenshot(win, 'free-time-saved.png')
win.setHeight(420)
screenshot(win, 'free-time-compact.png')
click('schoolModeTab')
assert state()['page'] == 'school'
win.setHeight(660)
QMetaObject.invokeMethod(probe, 'scale')
screenshot(win, 'school-large-text.png')
click('freeTimeTab')
screenshot(win, 'free-time-large-text.png')
win.close()
QTest.qWait(20)
assert state()['password'] == '', state()
probe.close()

bar = load('BarProbe.qml')
count = bar.findChild(QQuickItem, 'freeTimeCountdown')
widget = bar.findChild(QQuickItem, 'barWidget')
assert count.isVisible() and count.property('text') == '29:58'
assert widget.width() >= count.width()+20
screenshot(bar, 'free-bar-panel.png')
QMetaObject.invokeMethod(bar, 'school')
assert not count.isVisible()
screenshot(bar, 'school-bar-panel.png')
bar.close()
print(f'PASS: tabs, typed 45-minute save, stdin authentication, close cleanup and mode countdown. Inspect screenshots in {base}.')
