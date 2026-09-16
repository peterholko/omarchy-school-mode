import QtQuick
import QtQuick.Window
import qs.Commons
import "@PLUGIN_URL@" as School
Window {
  id: root
  visible: true; width: 388; height: 280; color: Color.background
  property QtObject modeService: QtObject {
    property bool schoolMode: false
    property bool schoolEnabled: true
    property bool freeTimeReady: true
    property int timerVersion: 1
    property string mode: schoolMode ? "school" : "free"
    property string modeReason: "parent"
    property string countdownText: "29:58"
    property var allowedDesktopIds: ["chromium", "org.gnome.Nautilus"]
    property string userName: "linnea"
    property string schoolUntil: ""
    property string schoolLabel: ""
    property var blockedPeriods: []
  }
  property QtObject bar: QtObject {
    property QtObject shell: QtObject { function serviceFor(name) { return root.modeService } }
    property bool vertical: false
    property real barSize: 32
    property color foreground: Color.foreground
    property color barForeground: Color.foreground
    property color urgent: Color.urgent
    property string fontFamily: "Menlo"
    property bool foregroundAnimationEnabled: false
    function hideTooltip(item) {}
    function showTooltip(item, text) {}
  }
  School.BarWidget { id: widget; objectName: "barWidget"; bar: root.bar; x: 20; y: 8 }
  School.Panel { id: panel; service: root.modeService; x: 24; y: 58 }
  function school() { modeService.schoolMode = true }
  Component.onCompleted: { Style.fontFamily="Menlo"; Style.fontBaseSize=12; panel.open() }
}
