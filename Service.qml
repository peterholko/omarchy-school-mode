import QtQuick
import Quickshell
import Quickshell.Io
import "Allowlist.js" as Allowlist
import "ModeState.js" as ModeState

Item {
  id: root
  property var shell: null
  property var manifest: null
  property var pluginRegistry: null
  property string omarchyPath: Quickshell.env("OMARCHY_PATH")
  readonly property string userName: Quickshell.env("USER")
  readonly property string statusPath: "/var/lib/omarchy-kids-controls/status/" + userName + "/school-mode/status.json"
  readonly property string desktopTool: decodeURIComponent(Qt.resolvedUrl("school-desktop.py").toString().replace(/^file:\/\//, ""))
  property bool connected: false
  property bool schoolEnabled: false
  property string mode: "free"
  property string modeReason: ""
  property string schoolUntil: ""
  property string schoolLabel: ""
  property var allowedDesktopIds: []
  property var blockedPeriods: []
  property string desktopError: ""
  readonly property bool schoolMode: schoolEnabled && mode === "school"
  signal allowlistChanged()

  function isAllowed(desktopId) { return Allowlist.contains(allowedDesktopIds, desktopId) }
  function guardAppLaunch() { if (!desktop.running) desktop.running = true }
  function removalReady() { return schoolEnabled ? "disable school enrollment first" : "ready" }
  function loadStatus(rawText) {
    var state = ModeState.parseStatus(rawText)
    if (!state.valid) { connected = false; return }
    connected = true
    schoolEnabled = state.enabled
    mode = state.mode
    modeReason = state.reason
    schoolUntil = state.schoolUntil
    schoolLabel = state.schoolLabel
    blockedPeriods = state.blockedPeriods
    var ids = Allowlist.normalizeIds(state.schoolApps)
    if (JSON.stringify(ids) !== JSON.stringify(allowedDesktopIds)) {
      allowedDesktopIds = ids
      allowlistChanged()
    }
  }
  FileView {
    id: statusFile
    path: root.statusPath
    watchChanges: true
    onFileChanged: reload()
    onLoaded: root.loadStatus(text())
    onLoadFailed: root.connected = false
  }
  Process {
    id: desktop
    command: ["python3", "-I", root.desktopTool, "sync"]
    stdout: StdioCollector { id: desktopOutput; waitForEnd: true }
    onExited: function(code) {
      try { root.desktopError = JSON.parse(desktopOutput.text).error || "" }
      catch (error) { root.desktopError = code === 0 ? "" : "School desktop setup needs attention" }
    }
  }
  Timer {
    interval: 3000
    running: true
    repeat: true
    triggeredOnStart: true
    onTriggered: {
      statusFile.reload()
      if (!desktop.running) desktop.running = true
    }
  }
  Component.onDestruction: Quickshell.execDetached(["python3", "-I", desktopTool, "restore"])
}
