import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons

// Display only: PAM and the root service still decide whether to unlock.
Rectangle {
  id: root
  objectName: "schoolParentLockNotice"
  readonly property string userName: Quickshell.env("USER") || Quickshell.env("LOGNAME")
  readonly property string statusPath: "/var/lib/omarchy-kids-controls/status/" + userName + "/school-mode/status.json"
  property bool parentOnly: false
  visible: parentOnly
  implicitHeight: parentOnly ? message.implicitHeight + Style.space(24) : 0
  radius: Style.cornerRadius
  color: Color.background
  border.width: Style.space(1)
  border.color: Qt.rgba(Color.foreground.r, Color.foreground.g, Color.foreground.b, 0.25)

  function loadStatus(raw) {
    var status = null
    try { status = JSON.parse(raw) } catch (error) {}
    parentOnly = !!status && status.schemaVersion === 1 && status.enabled === true
      && status.mode === "free" && status.freeTimeTimerVersion === 1
      && status.freeTimeReady === true && status.freeTimeExpired === true
  }

  Column {
    id: message
    x: Style.space(16)
    y: Style.space(12)
    width: Math.max(0, parent.width - Style.space(32))
    spacing: Style.space(6)
    Text {
      objectName: "parentUnlockTitle"
      width: parent.width
      text: "Parent password required"
      textFormat: Text.PlainText
      wrapMode: Text.WordWrap
      horizontalAlignment: Text.AlignHCenter
      color: Color.foreground
      font.family: Style.font.family
      font.pixelSize: Style.font.heading
      font.weight: Font.DemiBold
    }
    Text {
      objectName: "parentUnlockExplanation"
      width: parent.width
      text: "Free Time has ended. Ask a parent to unlock and return to School Mode."
      textFormat: Text.PlainText
      wrapMode: Text.WordWrap
      horizontalAlignment: Text.AlignHCenter
      color: Color.foreground
      font.family: Style.font.family
      font.pixelSize: Style.font.body
    }
  }

  FileView {
    id: statusFile
    path: root.statusPath
    watchChanges: true
    printErrors: false
    onFileChanged: reload()
    onLoaded: root.loadStatus(text())
    onLoadFailed: root.parentOnly = false
  }
  Timer {
    interval: 2000
    repeat: true
    running: true
    triggeredOnStart: true
    onTriggered: statusFile.reload()
  }
}
