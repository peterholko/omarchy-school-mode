"""Exercise Capture and Keybindings with the installed Omarchy menu renderer.

Requires PySide6. Only window hosting, file reads and process/guard responses
are adapted for portable Qt; no recording, desktop command or service starts.
"""
import argparse
import json
import os
from pathlib import Path
import shutil

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')
from PySide6.QtCore import QObject, QPointF, QUrl, Slot, Qt
from PySide6.QtGui import QGuiApplication, QFontDatabase
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickWindow
from PySide6.QtTest import QTest

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--omarchy', required=True, type=Path)
parser.add_argument('--output', required=True, type=Path)
parser.add_argument('--font', action='append', default=[], type=Path)
parser.add_argument('--font-family', default='Menlo')
args = parser.parse_args()
base = args.output.resolve()
imports = base / 'qml'
host = base / 'host'
shutil.copytree(ROOT / 'tests/visual-fixtures/Quickshell', imports / 'Quickshell', dirs_exist_ok=True)
shutil.copytree(args.omarchy / 'shell/Ui', imports / 'qs/Ui', dirs_exist_ok=True)
commons = imports / 'qs/Commons'
commons.mkdir(parents=True, exist_ok=True)
for name in ('Style.qml', 'Border.qml', 'BorderGeometry.js', 'Util.qml'):
    shutil.copyfile(args.omarchy / 'shell/Commons' / name, commons / name)
(commons / 'Color.qml').write_text((ROOT / 'tests/visual-fixtures/qs/Commons/Color.qml').read_text().replace(
    '  property var shellValues:', '''  property var menu: ({background: "#fff5fa", text: "#573554", border: "#573554",
    scrim: "#18251b2d", selectedBackground: "#efe2ee", selectedText: "#ef3989", selectedBorder: "transparent"})
  property var shellValues:'''))
(commons / 'qmldir').write_text('module qs.Commons\n' + ''.join(
    f'singleton {name} 1.0 {name}.qml\n' for name in ('Style', 'Border', 'Color', 'Util')))
(imports / 'Quickshell/qmldir').write_text('module Quickshell\nsingleton Quickshell 1.0 Quickshell.qml\nPanelWindow 1.0 PanelWindow.qml\n')
(imports / 'Quickshell/Quickshell.qml').write_text((imports / 'Quickshell/Quickshell.qml').read_text().replace(
    'return "/nonexistent-school-ui-qa"', 'return name === "HOME" ? "/nonexistent-school-ui-qa" : ""'))
(imports / 'Quickshell/PanelWindow.qml').write_text('''import QtQuick
import QtQuick.Window
Window {
  objectName: "captureMenuWindow"
  width: 1280; height: 900
  // The offscreen platform does not deliver a native resize event.
  onWidthChanged: contentItem.width = width
  onHeightChanged: contentItem.height = height
  Component.onCompleted: { contentItem.width = width; contentItem.height = height }
}
''')
(imports / 'Quickshell/Io/FileView.qml').write_text('''import QtQuick
QtObject {
  property string path: ""
  property bool printErrors: false
  property bool watchChanges: false
  property string contents: ""
  signal loaded(); signal loadFailed(); signal fileChanged()
  function text() { return contents }
  function reload() {
    contents = CaptureFixture.readFile(path)
    if (contents) loaded(); else loadFailed()
  }
  onPathChanged: Qt.callLater(reload)
  Component.onCompleted: reload()
}
''')
(imports / 'Quickshell/Io/SplitParser.qml').write_text('import QtQuick\nQtObject { signal read(string data) }\n')
(imports / 'Quickshell/Io/qmldir').write_text('module Quickshell.Io\n' + ''.join(
    f'{name} 1.0 {name}.qml\n' for name in ('FileView', 'Process', 'SplitParser', 'StdioCollector')))
(imports / 'Quickshell/Io/Process.qml').write_text('''import QtQuick
QtObject {
  id: root
  property var command: []
  property bool running: false
  property var stdout: null
  signal exited(int code, int status)
  onRunningChanged: {
    if (!running) return
    Qt.callLater(function() {
      var output = CaptureFixture.output(root.command)
      if (root.stdout && typeof root.stdout.read === "function")
        output.split("\\n").filter(Boolean).forEach(function(line) { root.stdout.read(line) })
      if (root.stdout && typeof root.stdout.streamFinished === "function") {
        root.stdout.text = output
        root.stdout.streamFinished()
      }
      root.running = false
      root.exited(0, 0)
    })
  }
}
''')
native_dir = host / 'shell/plugins/menu'
native_dir.mkdir(parents=True, exist_ok=True)
source = (args.omarchy / 'shell/plugins/menu/Menu.qml').read_text()
omitted = ('import Quickshell.Wayland', 'WlrLayershell.', 'exclusionMode: ExclusionMode.Ignore',
           'anchors { top: true; bottom: true; left: true; right: true }')
(native_dir / 'Menu.qml').write_text('\n'.join(line for line in source.splitlines()
    if not any(line.strip().startswith(prefix) for prefix in omitted)) + '\n')
shutil.copyfile(args.omarchy / 'shell/plugins/menu/MenuModel.js', native_dir / 'MenuModel.js')
shutil.copytree(ROOT / 'tests/fixtures/shell/services', host / 'shell/services', dirs_exist_ok=True)
(base / 'Probe.qml').write_text('''import QtQuick
import Quickshell
import qs.Commons
import "@PLUGIN@" as School
import "host/shell/services"
Item {
  id: root
  property alias mode: service
  property alias plugin: menu
  property var rendered: menu.item
  property var commands: Quickshell.detachedCommands
  AppLibrary { id: apps }
  QtObject {
    id: service
    property bool connected: true
    property bool schoolEnabled: true
    property bool schoolMode: true
    property var allowedDesktopIds: ["chromium", "org.gnome.Nautilus"]
    signal allowlistChanged()
  }
  QtObject {
    id: api
    property var appLibrary: apps
    property var pluginRegistry: null
    property var barWidgetRegistry: null
    function serviceFor(id) { return service }
  }
  School.Menu {
    id: menu
    omarchyPath: "@HOST@"
    shell: api
    service: root.mode
    manifest: ({id: "io.github.peterholko.school-mode"})
  }
  Component.onCompleted: Style.fontFamily = @FONT@
}
'''.replace('@PLUGIN@', ROOT.as_uri()).replace('@HOST@', str(host)).replace('@FONT@', json.dumps(args.font_family)))


class CaptureFixture(QObject):
    webcam = False
    recording = False

    @Slot(str, result=str)
    def readFile(self, path):
        file = Path(path)
        if file.parent == ROOT and file.name in ('school-menu.jsonc', 'free-time-menu.jsonc', 'empty-menu.jsonc'):
            return file.read_text()
        return ''

    @Slot('QVariantList', result=str)
    def output(self, command):
        if command and command[0] == 'fc-match':
            return args.font_family
        if command and command[0] == 'hyprctl':
            return '{"int":0}'
        return ('style:w:1\nstyle.theme:w:1\nstyle.background:w:1\n'
                f'trigger.capture.screenrecord.webcam:w:{int(self.webcam)}\n'
                f'trigger.capture.screenrecord.stop:w:{int(self.recording)}')


app = QGuiApplication.instance() or QGuiApplication([])
QFontDatabase.addApplicationFont(str(args.omarchy / 'default/fonts/omarchy/omarchy.ttf'))
for font in args.font:
    assert QFontDatabase.addApplicationFont(str(font)) >= 0, font
engine = QQmlEngine()
engine.addImportPath(str(imports))
fixture = CaptureFixture()
engine.rootContext().setContextProperty('CaptureFixture', fixture)
component = QQmlComponent(engine, QUrl.fromLocalFile(str(base / 'Probe.qml')))
assert not component.isError(), [error.toString() for error in component.errors()]
probe = component.create()
assert probe is not None
QTest.qWait(100)
engine.globalObject().setProperty('probe', engine.newQObject(probe))


def js(source):
    result = engine.evaluate(source)
    assert not result.isError(), result.toString()
    return result.toVariant()


def open_menu(route):
    js('probe.plugin.close()')
    js('probe.plugin.open(' + json.dumps(json.dumps({'menu': route, 'fontFamily': args.font_family})) + ')')
    QTest.qWait(120)
    assert js('probe.rendered.activeMenu') == route
    assert js('probe.rendered.opened && probe.rendered.rowsLoaded')


def capture(name):
    QTest.qWait(80)
    cards = [item for item in window.contentItem().childItems()
             if item.metaObject().className().startswith('BorderSurface')]
    assert len(cards) == 1
    card = cards[0]
    assert 0 <= card.x() and card.x() + card.width() <= window.width()
    assert 0 <= card.y() and card.y() + card.height() <= window.height()
    assert window.grabWindow().save(str(base / name))


def visual_items(item):
    yield item
    for child in item.childItems():
        yield from visual_items(child)


def click_label(label):
    for item in visual_items(window.contentItem()):
        if item.property('text') == label and item.isVisible():
            point = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()
            assert 0 <= point.x() < window.width() and 0 <= point.y() < window.height(), (label, point)
            QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
            QTest.qWait(40)
            return
    raise AssertionError('Visible menu row not found: ' + label)


for mode in ('school', 'free'):
    js('probe.mode.schoolMode = ' + str(mode == 'school').lower())
    open_menu('trigger.capture')
    window = next(win for win in app.allWindows() if win.objectName() == 'captureMenuWindow')
    assert isinstance(window, QQuickWindow)
    capture(mode + '-capture.png')
    click_label('Screenrecord')
    QTest.qWait(80)
    assert js('probe.rendered.activeMenu') == 'trigger.capture.screenrecord'
    capture(mode + '-recording.png')
    click_label('With desktop audio')
    assert js('probe.commands.slice(-1)[0]') == ['bash', '-lc', 'omarchy-capture-screenrecording --with-desktop-audio']
    assert not js('probe.rendered.opened')
    open_menu('trigger.capture.screenrecord')
    assert not js('probe.rendered.whenResults["trigger.capture.screenrecord.webcam"]')
    assert not js('probe.rendered.whenResults["trigger.capture.screenrecord.stop"]')
    js('probe.rendered.goBack()')
    QTest.qWait(20)
    approved = js('probe.rendered.shell.appLibrary.sortedEntries("").map(function(row) { return row.entry.id })')
    assert {'chromium', 'org.gnome.Nautilus'} <= set(approved)
    assert not {'Discord', 'discord', 'steam'} & set(approved)
    open_menu('apps')
    capture(mode + '-launcher.png')
    click_label('Keybindings')
    assert js('probe.commands.slice(-1)[0]') == ['bash', '-lc',
        'omarchy-shell shell call io.github.peterholko.school-mode showKeybindings ""']
    assert js('probe.plugin.showKeybindings()') == 'ok'
    assert js('probe.commands.slice(-1)[0]') == ['bash', str(ROOT / 'keybindings')]
    # The helper's payload contract is exercised by test_keybindings.py.
    payload = {'mode': 'select', 'prompt': 'Keybindings', 'width': 800, 'maxHeight': 500,
               'options': ['SUPER + K → School / Free Time: Keybindings',
                           'SUPER + CTRL + C → School / Free Time: Capture',
                           'ALT + PRINT → School / Free Time: Screenrecording',
                           'PRINT → Screenshot']}
    js('probe.plugin.open(' + json.dumps(json.dumps(payload)) + ')')
    capture(mode + '-keybindings.png')
    assert not js('probe.rendered.requestActive')
    count = js('probe.commands.length')
    for letter in 'capture':
        QTest.keyClick(window, getattr(Qt, 'Key_' + letter.upper()))
    QTest.qWait(60)
    assert js('probe.rendered.filterText') == 'capture'
    capture(mode + '-keybindings-search.png')
    QTest.keyClick(window, Qt.Key_Return)
    assert not js('probe.rendered.opened')
    assert js('probe.commands.length') == count
    js('probe.plugin.open(' + json.dumps(json.dumps(payload)) + ')')
    QTest.qWait(40)
    QTest.keyClick(window, Qt.Key_Escape)
    assert not js('probe.rendered.opened')
    assert js('probe.commands.length') == count

fixture.webcam = True
fixture.recording = True
open_menu('trigger.capture.screenrecord')
assert js('probe.rendered.whenResults["trigger.capture.screenrecord.webcam"]')
assert js('probe.rendered.whenResults["trigger.capture.screenrecord.stop"]')
capture('recording-active-webcam.png')
click_label('Stop Screenrecording')
assert js('probe.commands.slice(-1)[0]') == ['bash', '-lc', 'omarchy-capture-screenrecording --stop-recording']
open_menu('trigger.capture.screenrecord')
click_label('With desktop + microphone audio + webcam')
assert js('probe.commands.slice(-1)[0]') == ['bash', '-lc',
    'omarchy-capture-screenrecording --with-desktop-audio --with-microphone-audio --with-webcam']
window.setWidth(800)
window.setHeight(600)
window.contentItem().setWidth(800)
window.contentItem().setHeight(600)
open_menu('trigger.capture.screenrecord')
capture('recording-compact.png')
probe.deleteLater()
QTest.qWait(20)
print('PASS: actual menu rendering, capture actions, keybindings search/selection/cancel, mode transitions and recording/webcam guards. Inspect captures in ' + str(base))
