import QtQuick
import QtQuick.Window
import Quickshell
import qs.Commons
import "@PLUGIN_URL@" as School
Window {
  visible: true
  width: 1; height: 1
  id: root
  property QtObject modeService: QtObject {
    property string userName: "linnea"
    property var blockedPeriods: []
    property var allowedDesktopIds: []
  }
  School.SchoolSettingsWindow { id: settings; objectName: "settings"; service: root.modeService; clientPath: "/test-client" }
  function inspect(): string { return JSON.stringify({page: settings.settingsPage, commands: Quickshell.detachedCommands, writes: Quickshell.writes, note: settings.note, password: settings.password}) }
  function show() { settings.show("fixture-parent-secret", {users: {linnea: {profile: "child"}}, profiles: {child: {school_apps: [], free_time_minutes: 30, blocked_periods: [{enabled: true, mode: "free", label: "School", start: "08:30", end: "15:00", days:["mon","tue","wed","thu","fri"]}]}}}) }
  function scale() { Style.fontBaseSize = 16 }
  Component.onCompleted: { Style.fontFamily = "Menlo"; show() }
}
