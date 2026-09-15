import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Io
import qs.Ui
import qs.Commons
import "SchoolSchedule.js" as Schedule
import "Allowlist.js" as Allowlist

// Parent-authenticated school hours and optional apps. Settings stay in the
// school module; installing an app does not grant school access by itself.
Item {
  id: root

  property var service: null
  property string clientPath: ""
  property string password: ""
  property string note: ""
  property color noteColor: Color.foreground
  property var localPeriods: []
  property var localApps: []
  property string settingsPage: "school"
  property int localFreeTimeMinutes: 30
  property var pendingPatch: null
  property var activePatch: null
  readonly property bool savingApps: (activePatch !== null && activePatch.school_apps !== undefined)
    || (pendingPatch !== null && pendingPatch.school_apps !== undefined)
  readonly property var schoolAppChoices: [
    { desktopId: "io.github.peterholko.paw-post", name: "Paw Post", practice: "typing practice", controlName: "pawPostSchoolToggle" },
    { desktopId: "io.github.peterholko.number-grove", name: "Number Grove", practice: "arithmetic practice", controlName: "numberGroveSchoolToggle" },
    { desktopId: "io.github.peterholko.pawberry", name: "Pawberry Pet Hotel", practice: "step-by-step math", controlName: "pawberrySchoolToggle" }
  ]
  readonly property var installedAppIds: Allowlist.normalizeIds((DesktopEntries.applications.values || []).map(function(entry) {
    return entry ? entry.id : ""
  }))
  readonly property int totalPeriodLimit: 8
  readonly property var dayKeys: Schedule.DAYS
  readonly property var dayLabels: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
  readonly property string iconClose: "\uf00d"

  readonly property bool lightTheme: {
    var bg = Color.background
    return (0.299 * bg.r + 0.587 * bg.g + 0.114 * bg.b) > 0.5
  }
  readonly property color okColor: lightTheme ? "#3C7C4E" : "#5FA46B"
  readonly property color errColor: lightTheme ? "#B03434" : "#E06C6C"

  function fadeText(amount) {
    var foreground = Color.foreground
    var background = Color.background
    return Qt.rgba(foreground.r + (background.r - foreground.r) * amount,
                   foreground.g + (background.g - foreground.g) * amount,
                   foreground.b + (background.b - foreground.b) * amount, 1)
  }

  function show(passwordValue, config) {
    root.password = String(passwordValue || "")
    root.note = ""
    var user = root.service ? root.service.userName : ""
    var key = config && config.users && config.users[user] ? config.users[user].profile : ""
    var profile = config && config.profiles ? config.profiles[key || config.active_profile] : null
    root.localPeriods = Schedule.schoolPeriods(profile ? profile.blocked_periods : (root.service ? root.service.blockedPeriods : []))
    root.localApps = Allowlist.normalizeIds(profile ? profile.school_apps : (root.service ? root.service.allowedDesktopIds : []))
    root.localFreeTimeMinutes = profile && Number.isInteger(profile.free_time_minutes) ? profile.free_time_minutes : 30
    root.settingsPage = "school"
    win.visible = true
  }

  function close() {
    win.visible = false
    root.password = ""
    root.pendingPatch = null
  }

  function nonSchoolCount() {
    var source = root.service && root.service.blockedPeriods ? root.service.blockedPeriods : []
    return source.filter(function(period) { return !period || period.mode !== "free" }).length
  }

  function canAddPeriod() {
    return root.nonSchoolCount() + root.localPeriods.length < root.totalPeriodLimit
  }

  function writePeriods(schools) {
    root.localPeriods = Schedule.clonePeriods(schools)
    var allPeriods = Schedule.merge(root.service ? root.service.blockedPeriods : [], root.localPeriods)
    root.patch({ "blocked_periods": allPeriods })
  }

  function setPeriod(index, key, value) {
    var periods = Schedule.clonePeriods(root.localPeriods)
    if (index < 0 || index >= periods.length || periods[index][key] === value) return
    periods[index][key] = value
    root.writePeriods(periods)
  }

  function addPeriod() {
    if (!root.canAddPeriod()) return
    var periods = Schedule.clonePeriods(root.localPeriods)
    periods.push({
      label: "School",
      enabled: true,
      start: "08:30",
      end: "15:00",
      days: ["mon", "tue", "wed", "thu", "fri"],
      mode: "free"
    })
    root.writePeriods(periods)
  }

  function removePeriod(index) {
    var periods = Schedule.clonePeriods(root.localPeriods)
    if (index < 0 || index >= periods.length) return
    periods.splice(index, 1)
    root.writePeriods(periods)
  }

  function togglePeriodDay(index, day) {
    root.writePeriods(Schedule.toggleDay(root.localPeriods, index, day))
  }

  function setAppAllowed(desktopId, allowed) {
    if (root.password === "" || root.savingApps || (allowed && !Allowlist.contains(root.installedAppIds, desktopId))) return
    var apps = Allowlist.normalizeIds(root.localApps).filter(function(id) { return id !== desktopId })
    if (allowed) apps.push(desktopId)
    root.patch({ "school_apps": Allowlist.normalizeIds(apps) })
  }

  function saveTime(index, key, value, field) {
    var text = String(value || "").trim()
    if (Schedule.validTime(text)) {
      root.setPeriod(index, key, text)
      return
    }
    field.text = String(root.localPeriods[index][key] || "")
    root.note = "Use a 24-hour time such as 08:30."
    root.noteColor = root.errColor
  }

  function saveFreeTime(value) {
    var text = String(value).trim()
    var minutes = Number(text)
    if (!/^\d+$/.test(text) || !Number.isInteger(minutes) || minutes < 1 || minutes > 1440) {
      root.note = "Enter a whole number from 1 to 1440 minutes."
      root.noteColor = root.errColor
      return
    }
    root.localFreeTimeMinutes = minutes
    root.patch({ "free_time_minutes": minutes })
  }

  function patch(obj) {
    if (root.password === "") return
    // Day buttons are easy to click faster than a process can finish. Keep
    // the newest array for each setting, so an hours edit cannot discard an
    // app choice waiting for the same process.
    root.pendingPatch = Object.assign({}, root.pendingPatch || {}, obj)
    root.note = "Saving…"
    root.noteColor = root.fadeText(0.5)
    root.sendPendingPatch()
  }

  function sendPendingPatch() {
    if (patchProc.running || root.pendingPatch === null) return
    var next = root.pendingPatch
    root.pendingPatch = null
    root.activePatch = next
    patchProc.launched = false
    patchProc.pendingPassword = root.password
    patchProc.command = [root.clientPath, "--password-stdin", "config", "patch", JSON.stringify(next)]
    patchProc.running = true
  }

  function handlePatchReply(rawText) {
    var payload
    try { payload = JSON.parse(rawText) } catch (error) { payload = null }
    patchProc.pendingPassword = ""
    if (payload && payload.ok === true) {
      if (root.activePatch && root.activePatch.school_apps !== undefined)
        root.localApps = Allowlist.normalizeIds(root.activePatch.school_apps)
      root.note = root.pendingPatch !== null ? "Saving…" : "Saved."
      root.noteColor = root.okColor
    } else {
      root.pendingPatch = null
      root.noteColor = root.errColor
      if (payload && payload.error === "password_locked_out")
        root.note = "Too many tries. Close this window and unlock it again later."
      else if (payload && payload.error === "bad_password")
        root.note = "The parent password is no longer accepted. Close this window and unlock it again."
      else
        root.note = "Could not save settings. Try again."
    }
    root.activePatch = null
    Qt.callLater(root.sendPendingPatch)
  }

  Process {
    id: patchProc
    property bool launched: false
    property string pendingPassword: ""
    stdinEnabled: true
    onStarted: { launched = true; write(pendingPassword + "\n") }
    stdout: StdioCollector { id: patchOut; waitForEnd: true }
    onExited: root.handlePatchReply(patchOut.text)
    onRunningChanged: if (!running && !launched) root.handlePatchReply("")
  }

  FloatingWindow {
    id: win
    visible: false
    title: "School Mode / Free Time settings"
    color: Color.background
    implicitWidth: 520
    implicitHeight: 660
    minimumSize: Qt.size(520, 420)
    maximumSize: Qt.size(520, 760)
    onVisibleChanged: if (!visible) { root.password = ""; root.pendingPatch = null }

    FocusScope {
      anchors.fill: parent
      focus: true

      Keys.priority: Keys.AfterItem
      Keys.onPressed: function(event) {
        if (event.key === Qt.Key_Escape) {
          root.close()
          event.accepted = true
        }
      }

      Row {
        id: pageTabs
        anchors.top: parent.top; anchors.left: parent.left; anchors.right: parent.right
        anchors.margins: Style.space(20)
        spacing: Style.space(8)
        Button {
          objectName: "schoolModeTab"
          width: (pageTabs.width - pageTabs.spacing) / 2
          text: "School Mode"; selected: root.settingsPage === "school"; bordered: true; focusable: true
          onClicked: root.settingsPage = "school"
        }
        Button {
          objectName: "freeTimeTab"
          width: (pageTabs.width - pageTabs.spacing) / 2
          text: "Free Time"; selected: root.settingsPage === "free"; bordered: true; focusable: true
          onClicked: root.settingsPage = "free"
        }
      }

      ScrollView {
        id: scrollArea
        anchors.top: pageTabs.bottom; anchors.bottom: parent.bottom
        anchors.left: parent.left; anchors.right: parent.right
        anchors.margins: Style.space(20)
        clip: true
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

        Column {
          id: content
          width: scrollArea.availableWidth
          spacing: Style.space(14)

          Column {
            objectName: "schoolSettingsPage"
            width: content.width; spacing: Style.space(14)
            visible: root.settingsPage === "school"
            PanelSectionHeader {
              text: "SCHOOL APPS"
              foreground: Color.foreground
            }

            Repeater {
              model: root.schoolAppChoices
              delegate: Toggle {
                required property var modelData
                readonly property bool installed: Allowlist.contains(root.installedAppIds, modelData.desktopId)
                objectName: modelData.controlName
                width: content.width
                label: modelData.name
                description: root.savingApps ? "Saving…" : (installed
                  ? "Allow " + modelData.practice + " during School Mode."
                  : "Install " + modelData.name + " to make " + modelData.practice + " available.")
                checked: Allowlist.contains(root.localApps, modelData.desktopId)
                enabled: root.password !== "" && !root.savingApps && (installed || checked)
                opacity: enabled || root.savingApps ? 1 : 0.6
                onClicked: root.setAppAllowed(modelData.desktopId, !checked)
              }
            }

            PanelSeparator { width: parent.width }

            PanelSectionHeader {
              text: "SCHOOL HOURS"
              foreground: Color.foreground
            }

            Text {
              textFormat: Text.PlainText
              text: "At these times the laptop enters School Mode automatically. Only a parent can return it to Free Time."
              width: parent.width
              wrapMode: Text.WordWrap
              color: root.fadeText(0.5)
              font.family: Style.font.family
              font.pixelSize: Style.font.caption
            }

            PanelSeparator { width: parent.width }

            Text {
              textFormat: Text.PlainText
              visible: root.localPeriods.length === 0
              text: "No school hours yet. Add a schedule to turn School Mode on automatically."
              width: parent.width
              wrapMode: Text.WordWrap
              color: root.fadeText(0.5)
              font.family: Style.font.family
              font.pixelSize: Style.font.body
            }

            Repeater {
              model: root.localPeriods

              delegate: Column {
                id: periodRow
                required property var modelData
                required property int index
                width: content.width
                spacing: Style.space(8)

                Row {
                  id: periodTop
                  width: parent.width
                  spacing: Style.space(8)

                  ToggleSwitch {
                    id: periodToggle
                    anchors.verticalCenter: parent.verticalCenter
                    checked: periodRow.modelData.enabled === true
                    onToggled: root.setPeriod(periodRow.index, "enabled", !periodRow.modelData.enabled)
                  }

                  TextField {
                    width: periodTop.width - periodToggle.width - periodRemove.width - periodTop.spacing * 2
                    text: String(periodRow.modelData.label || "School")
                    placeholderText: "School"
                    activeFocusOnTab: true
                    onEditingFinished: root.setPeriod(periodRow.index, "label", text.trim() || "School")
                  }

                  PanelActionButton {
                    id: periodRemove
                    iconText: root.iconClose
                    tooltipText: "Remove these school hours"
                    foreground: Color.foreground
                    hoverColor: root.errColor
                    size: Style.space(22)
                    focusable: true
                    anchors.verticalCenter: parent.verticalCenter
                    onClicked: root.removePeriod(periodRow.index)
                  }
                }

                Row {
                  spacing: Style.space(8)

                  Text {
                    textFormat: Text.PlainText
                    text: "from"
                    color: root.fadeText(0.4)
                    font.family: Style.font.family
                    font.pixelSize: Style.font.body
                    anchors.verticalCenter: parent.verticalCenter
                  }
                  TextField {
                    id: startField
                    width: Style.space(64)
                    text: String(periodRow.modelData.start || "")
                    activeFocusOnTab: true
                    onEditingFinished: root.saveTime(periodRow.index, "start", text, startField)
                  }
                  Text {
                    textFormat: Text.PlainText
                    text: "until"
                    color: root.fadeText(0.4)
                    font.family: Style.font.family
                    font.pixelSize: Style.font.body
                    anchors.verticalCenter: parent.verticalCenter
                  }
                  TextField {
                    id: endField
                    width: Style.space(64)
                    text: String(periodRow.modelData.end || "")
                    activeFocusOnTab: true
                    onEditingFinished: root.saveTime(periodRow.index, "end", text, endField)
                  }
                }

                Row {
                  spacing: Style.space(4)
                  Repeater {
                    model: root.dayKeys.length
                    delegate: Button {
                      text: root.dayLabels[index]
                      bordered: true
                      focusable: true
                      selected: (periodRow.modelData.days || []).indexOf(root.dayKeys[index]) >= 0
                      onClicked: root.togglePeriodDay(periodRow.index, root.dayKeys[index])
                    }
                  }
                }

                PanelSeparator {
                  width: parent.width
                  visible: periodRow.index < root.localPeriods.length - 1
                }
              }
            }

            Row {
              spacing: Style.space(8)

              Button {
                text: "Add school time"
                focusable: true
                enabled: root.canAddPeriod()
                onClicked: root.addPeriod()
              }

              Text {
                textFormat: Text.PlainText
                visible: !root.canAddPeriod()
                text: "All eight school schedules are in use."
                color: root.fadeText(0.5)
                font.family: Style.font.family
                font.pixelSize: Style.font.caption
                anchors.verticalCenter: parent.verticalCenter
              }
            }
          }

          Column {
            objectName: "freeTimeSettingsPage"
            width: content.width; spacing: Style.space(14)
            visible: root.settingsPage === "free"
            PanelSectionHeader { text: "FREE TIME ALLOWANCE"; foreground: Color.foreground }
            Text {
              width: parent.width; wrapMode: Text.WordWrap
              text: "Each time a parent starts Free Time, the laptop gets this many minutes."
              color: root.fadeText(0.35); font.family: Style.font.family; font.pixelSize: Style.font.body
            }
            Row {
              spacing: Style.space(10)
              TextField {
                id: minutesField
                objectName: "freeTimeMinutesField"
                width: Style.space(86)
                text: String(root.localFreeTimeMinutes)
                validator: IntValidator { bottom: 1; top: 1440 }
                inputMethodHints: Qt.ImhDigitsOnly
                activeFocusOnTab: true
                onAccepted: root.saveFreeTime(text)
              }
              Text {
                text: "minutes"; anchors.verticalCenter: parent.verticalCenter
                color: Color.foreground; font.family: Style.font.family; font.pixelSize: Style.font.body
              }
              Button {
                objectName: "saveFreeTimeButton"
                text: "Save"; focusable: true
                enabled: root.password !== "" && !patchProc.running
                onClicked: root.saveFreeTime(minutesField.text)
              }
            }
            Text {
              width: parent.width; wrapMode: Text.WordWrap
              text: "Default: 30 minutes. Changes apply to the next allowance."
              color: root.fadeText(0.5); font.family: Style.font.family; font.pixelSize: Style.font.caption
            }
            PanelSeparator { width: parent.width }
            PanelSectionHeader { text: "WHEN TIME RUNS OUT"; foreground: Color.foreground }
            Text {
              width: parent.width; wrapMode: Text.WordWrap
              text: "The screen locks. Enter the parent password to unlock and return to School Mode. A parent must start Free Time again for another allowance."
              color: root.fadeText(0.35); font.family: Style.font.family; font.pixelSize: Style.font.body
            }
            Text {
              width: parent.width; wrapMode: Text.WordWrap
              text: "Before time runs out, your child can unlock normally. The countdown continues while the screen is locked or the laptop sleeps. Returning to School Mode cancels it. School Mode has no timer lock."
              color: root.fadeText(0.5); font.family: Style.font.family; font.pixelSize: Style.font.caption
            }
          }

          PanelSeparator { width: parent.width }

          Row {
            width: parent.width

            Text {
              textFormat: Text.PlainText
              text: root.note !== "" ? root.note : (root.settingsPage === "free" ? "Applies to the next allowance." : "Changes apply immediately.")
              color: root.note !== "" ? root.noteColor : root.fadeText(0.5)
              font.family: Style.font.family
              font.pixelSize: Style.font.caption
              width: parent.width - closeButton.width
              elide: Text.ElideRight
              anchors.verticalCenter: parent.verticalCenter
            }

            Button {
              id: closeButton
              text: "Close"
              focusable: true
              onClicked: root.close()
            }
          }
        }
      }
    }
  }
}
