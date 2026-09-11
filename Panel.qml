import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui
import "ModeState.js" as ModeState

// The mode pill's panel: which mode, why, the school apps, and the switch.
// School mode is the kid's to start any time; choosing Free Time is always the
// parent's, so the panel asks for the parent password before sending the
// switch to the daemon over stdin. The gear uses the same check before
// opening school settings for hours and optional apps.
Panel {
  id: root
  moduleName: "io.github.peterholko.school-mode.mode"
  ipcTarget: "io.github.peterholko.school-mode.mode"

  property var anchorItem: null
  property var hostWidget: null
  property var service: null
  property string note: ""
  property bool noteIsError: false
  property bool askingParent: false
  property string pendingMode: ""
  property string pendingAction: ""
  readonly property bool checkingParent: (modeProc.running && modeProc.pendingPassword !== "") || settingsAuthProc.running

  readonly property var barIdentity: hostWidget || root
  readonly property bool schoolMode: service ? service.schoolMode === true : false
  readonly property string reasonLine: service ? ModeState.reasonLine({
    enabled: service.schoolEnabled, mode: service.mode, reason: service.modeReason,
    schoolUntil: service.schoolUntil, schoolLabel: service.schoolLabel }) : ""
  readonly property int schoolAppCount: service && service.allowedDesktopIds ? service.allowedDesktopIds.length : 0
  readonly property string clientPath: "/usr/bin/omarchy-kids-controls-school-client"
  readonly property color foreground: bar ? bar.foreground : Color.foreground
  readonly property color accent: Color.accent
  readonly property color dim: Qt.rgba(foreground.r, foreground.g, foreground.b, 0.58)
  readonly property color errorColor: Color.urgent
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family
  readonly property string iconGear: "\uf013"

  function open() {
    if (!root.checkingParent) {
      root.note = ""
      root.noteIsError = false
      root.askingParent = false
      root.pendingAction = ""
      root.pendingMode = ""
      passwordField.text = ""
    }
    root.controller.show()
  }
  function close() { root.controller.hide() }
  function toggle() { root.opened ? root.close() : root.open() }
  function closeForPopoutSwitch() { root.controller.hide() }

  function switchPanel(direction) {
    if (root.bar && typeof root.bar.switchPanelFrom === "function")
      return root.bar.switchPanelFrom(root.barIdentity, direction)
    return false
  }

  // The switch: School Mode without a password, Free Time with the parent password.
  // Ask before making a free-time request; the daemon validates the password.
  function requestMode(mode, password) {
    if (modeProc.running || settingsAuthProc.running) return
    root.pendingAction = "mode"
    root.pendingMode = mode
    if (mode === "free" && String(password || "").trim() === "") {
      root.askingParent = true
      root.note = "Enter the parent password to switch to free time."
      root.noteIsError = false
      passwordField.text = ""
      Qt.callLater(function() { passwordField.forceActiveFocus() })
      return
    }
    modeProc.pendingPassword = String(password || "")
    passwordField.text = ""
    root.note = ""
    root.noteIsError = false
    modeProc.launched = false
    modeProc.command = [root.clientPath, "--password-stdin", "mode", mode]
    modeProc.running = true
  }

  function switchMode() {
    requestMode(root.schoolMode ? "free" : "school", "")
  }

  function openSettings() {
    if (modeProc.running || settingsAuthProc.running) return
    root.pendingAction = "settings"
    root.pendingMode = ""
    root.askingParent = true
    root.note = "Enter the parent password to edit school hours and apps."
    root.noteIsError = false
    passwordField.text = ""
    Qt.callLater(function() { passwordField.forceActiveFocus() })
  }

  function authenticateSettings(password) {
    if (modeProc.running || settingsAuthProc.running) return
    settingsAuthProc.pendingPassword = String(password || "")
    passwordField.text = ""
    root.note = ""
    root.noteIsError = false
    settingsAuthProc.launched = false
    settingsAuthProc.command = [root.clientPath, "--password-stdin", "config", "get"]
    settingsAuthProc.running = true
  }

  function submitParent() {
    if (!root.askingParent || root.checkingParent) return
    var password = passwordField.text
    if (password.trim() === "") return
    if (root.pendingAction === "settings") authenticateSettings(password)
    else if (root.pendingAction === "mode") requestMode(root.pendingMode, password)
  }

  function handleModeReply(rawText) {
    var payload
    modeProc.pendingPassword = ""
    try { payload = JSON.parse(rawText) } catch (e) { payload = null }
    passwordField.text = ""
    if (payload && payload.ok === true) {
      root.askingParent = false
      root.pendingAction = ""
      root.note = payload.mode === "school" ? "School mode is on." : "Free time."
      root.noteIsError = false
      return
    }
    var error = payload ? String(payload.error || "") : ""
    if (error === "parent_required") {
      root.pendingAction = "mode"
      root.askingParent = true
      root.note = payload.until
        ? "It is " + String(payload.label || "school").toLowerCase() + " until " + String(payload.until) + ". A parent can take free time."
        : "Only a parent can switch School Mode back to Free Time."
      root.noteIsError = false
      Qt.callLater(function() { passwordField.forceActiveFocus() })
      return
    }
    root.noteIsError = true
    if (error === "bad_password") root.note = "That is not the parent password."
    else if (error === "password_locked_out") root.note = "Too many tries. Wait " + payload.retry_in_seconds + " s."
    else root.note = "Could not switch: " + (error || "no answer from school mode")
  }

  function handleSettingsReply(rawText) {
    var payload
    var password = settingsAuthProc.pendingPassword
    settingsAuthProc.pendingPassword = ""
    try { payload = JSON.parse(rawText) } catch (error) { payload = null }
    passwordField.text = ""
    if (payload && payload.ok === true) {
      root.askingParent = false
      root.pendingAction = ""
      schoolSettings.show(password, payload.config)
      root.close()
      return
    }
    root.noteIsError = true
    if (payload && payload.error === "password_locked_out")
      root.note = "Too many tries. Wait " + payload.retry_in_seconds + " s."
    else if (payload && payload.error === "bad_password")
      root.note = "That is not the parent password."
    else
      root.note = "Could not open school settings."
    Qt.callLater(function() { passwordField.forceActiveFocus() })
  }

  Process {
    id: modeProc
    property string pendingPassword: ""
    property bool launched: false
    stdinEnabled: true
    onStarted: { launched = true; write(pendingPassword + "\n") }
    stdout: StdioCollector { id: modeOut; waitForEnd: true }
    onExited: root.handleModeReply(modeOut.text)
    // A client that could not start at all comes as runningChanged alone,
    // no exited; the panel must not wait on it forever.
    onRunningChanged: if (!running && !launched) root.handleModeReply("")
  }

  Process {
    id: settingsAuthProc
    property string pendingPassword: ""
    property bool launched: false
    stdinEnabled: true
    onStarted: { launched = true; write(pendingPassword + "\n") }
    stdout: StdioCollector { id: settingsOut; waitForEnd: true }
    onExited: root.handleSettingsReply(settingsOut.text)
    onRunningChanged: if (!running && !launched) root.handleSettingsReply("")
  }

  SchoolSettingsWindow {
    id: schoolSettings
    service: root.service
    clientPath: root.clientPath
  }

  KeyboardPanel {
    id: panel
    anchorItem: root.anchorItem
    owner: root.barIdentity
    bar: root.bar
    open: root.opened
    focusTarget: root.askingParent ? passwordField : keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(340))
    contentHeight: panel.fittedContentHeight(contentColumn.implicitHeight, Style.space(420))

    Item {
      id: keyCatcher
      anchors.fill: parent
      focus: true
      Keys.onPressed: function(event) {
        if (event.key === Qt.Key_Escape) { root.close(); event.accepted = true }
        else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) { root.switchMode(); event.accepted = true }
      }

      Column {
        id: contentColumn
        width: parent.width
        spacing: Style.space(10)

        PanelHero {
          width: parent.width
          foreground: root.foreground
          title: root.schoolMode ? "School mode" : "Free time"
          detail: root.schoolMode ? root.schoolAppCount + " apps" : "everything"
          meta: root.reasonLine
          iconComponent: Component {
            Text {
              textFormat: Text.PlainText
              text: root.schoolMode ? "\uf02d" : "\uf185"
              color: root.schoolMode ? root.accent : root.foreground
              font.family: Style.font.family
              font.pixelSize: Style.font.display
            }
          }
        }

        Text {
          textFormat: Text.PlainText
          width: parent.width
          wrapMode: Text.WordWrap
          text: root.schoolMode
            ? "The menu shows the school apps, their shortcuts alone work, notifications are quiet, and the browser keeps your account. Free-time windows are parked and come back after."
            : "Free Time shows the approved school and creativity apps and the three learning games. Notifications and your browser account stay available. School hours switch to School Mode automatically."
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
        }

        Row {
          width: parent.width
          spacing: Style.space(8)

          Button {
            id: modeButton
            width: parent.width - settingsButton.width - parent.spacing
            text: root.schoolMode ? "Back to free time" : "Start school mode"
            bordered: true
            selected: !root.schoolMode
            focusable: true
            enabled: !modeProc.running && !settingsAuthProc.running
              && root.service && root.service.schoolEnabled === true
            onClicked: root.switchMode()
          }

          PanelActionButton {
            id: settingsButton
            iconText: root.iconGear
            tooltipText: "School settings"
            foreground: root.foreground
            size: Style.spacing.controlHeight
            focusable: true
            bordered: true
            enabled: !modeProc.running && !settingsAuthProc.running
              && root.service && root.service.schoolEnabled === true
            onClicked: root.openSettings()
          }
        }

        Column {
          width: parent.width
          spacing: Style.space(6)
          visible: root.askingParent

          ParentPasswordField {
            id: passwordField
            width: parent.width
            password: true
            checking: root.checkingParent
            activeFocusOnTab: true
            Keys.onPressed: function(event) {
              if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) { root.submitParent(); event.accepted = true }
              else if (event.key === Qt.Key_Escape) {
                if (root.checkingParent) {
                  root.close()
                } else {
                  root.askingParent = false
                  root.pendingAction = ""
                  root.note = ""
                }
                event.accepted = true
              }
            }
          }
        }

        Text {
          textFormat: Text.PlainText
          visible: root.note !== ""
          width: parent.width
          wrapMode: Text.WordWrap
          text: root.note
          color: root.noteIsError ? root.errorColor : root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.body
        }
      }
    }
  }
}
