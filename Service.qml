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
  property int timerVersion: 0
  property bool freeTimeReady: false
  property int freeTimeMinutes: 30
  property int freeTimeRemainingSeconds: 0
  property bool freeTimeExpired: false
  property double countdownReadAt: Date.now()
  property double countdownNow: Date.now()
  property string countdownSnapshot: ""
  readonly property int countdownSeconds: schoolMode ? 0 : Math.max(0, freeTimeRemainingSeconds - Math.max(0, Math.floor((countdownNow - countdownReadAt) / 1000)))
  readonly property string countdownText: Math.floor(countdownSeconds / 60) + ":" + String(countdownSeconds % 60).padStart(2, "0")
  readonly property bool schoolMode: schoolEnabled && mode === "school"
  signal allowlistChanged()

  function isAllowed(desktopId) { return Allowlist.contains(allowedDesktopIds, desktopId) }
  function guardAppLaunch() { if (!desktop.running) desktop.running = true }
  function removalReady() { return schoolEnabled ? "disable school enrollment first" : "ready" }
  function loadStatus(rawText) {
    var state = ModeState.parseStatus(rawText)
    if (!state.valid) { connected = false; return }
    var changed = !connected || schoolEnabled !== state.enabled || mode !== state.mode
    connected = true
    schoolEnabled = state.enabled
    mode = state.mode
    modeReason = state.reason
    schoolUntil = state.schoolUntil
    schoolLabel = state.schoolLabel
    blockedPeriods = state.blockedPeriods
    timerVersion = state.timerVersion
    freeTimeReady = state.timerReady
    freeTimeMinutes = state.freeTimeMinutes
    freeTimeRemainingSeconds = state.freeTimeRemainingSeconds
    freeTimeExpired = state.freeTimeExpired
    countdownNow = Date.now()
    var snapshot = JSON.stringify([state.updatedAt, state.enabled, state.mode, state.freeTimeRemainingSeconds, state.freeTimeExpired])
    // Polling an unchanged status file must not put seconds back on the clock.
    if (snapshot !== countdownSnapshot) {
      countdownSnapshot = snapshot
      countdownReadAt = countdownNow
    }
    var ids = Allowlist.normalizeIds(state.schoolApps)
    if (JSON.stringify(ids) !== JSON.stringify(allowedDesktopIds)) {
      allowedDesktopIds = ids
      allowlistChanged()
    }
    if (changed) guardAppLaunch()
  }
  FileView {
    id: statusFile
    path: root.statusPath
    watchChanges: true
    onFileChanged: reload()
    onLoaded: root.loadStatus(text())
    onLoadFailed: root.connected = false
  }
  Timer {
    interval: 1000; repeat: true
    running: root.connected && root.schoolEnabled && !root.schoolMode
    onTriggered: root.countdownNow = Date.now()
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
  // Shell shutdown, logout and plugin reload are not permission to release
  // desktop restrictions. Only explicit disable/unenrollment restores them.
}
