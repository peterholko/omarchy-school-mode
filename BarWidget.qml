import QtQuick
import qs.Commons
import qs.Ui as Ui

// The mode pill on the right of the bar, placed there by Service.qml: a book
// in school mode, a sun in free time, and a panel behind it that says why and
// lets the kid enter School Mode; choosing Free Time and editing the
// school-hours schedule require the parent password.
Ui.BarWidget {
  id: root
  moduleName: "io.github.peterholko.school-mode"

  readonly property var modeService: bar && bar.shell ? bar.shell.serviceFor("io.github.peterholko.school-mode") : null
  readonly property bool schoolMode: modeService ? modeService.schoolMode === true : false
  readonly property bool schoolEnabled: modeService ? modeService.schoolEnabled === true : false
  readonly property bool showCountdown: schoolEnabled && !schoolMode && modeService.timerVersion === 1
  readonly property bool opened: panelLoader.item ? panelLoader.item.opened === true : false
  readonly property bool popoutSwitchClosing: panelLoader.item ? panelLoader.item.popoutSwitchClosing === true : false
  readonly property real openPanelIndicatorWidth: button.opticalSize

  function injectPanel() {
    var target = panelLoader.item
    if (!target) return
    target.bar = root.bar
    target.settings = root.settings
    target.anchorItem = button
    target.hostWidget = root
    target.service = root.modeService
  }

  function open() { if (panelLoader.item) panelLoader.item.open() }
  function close() { if (panelLoader.item) panelLoader.item.close() }
  function togglePanel() { if (panelLoader.item) panelLoader.item.toggle() }
  function closeForPopoutSwitch() { if (panelLoader.item) panelLoader.item.closeForPopoutSwitch() }

  visible: schoolEnabled
  implicitWidth: schoolEnabled ? content.implicitWidth : 0
  implicitHeight: button.implicitHeight

  onBarChanged: injectPanel()
  onSettingsChanged: injectPanel()
  onModeServiceChanged: injectPanel()

  Loader {
    id: panelLoader
    active: true
    source: Qt.resolvedUrl("Panel.qml")
    visible: false
    onLoaded: {
      root.injectPanel()
      Qt.callLater(root.injectPanel)
    }
  }

  Row {
    id: content
    spacing: root.showCountdown ? Style.space(4) : 0
    Ui.BarIconButton {
      id: button
      bar: root.bar
      text: root.schoolMode ? "\uf02d" : "\uf185"
      slotSize: Style.bar.statusSlot
      opticalSize: Style.bar.iconCanvas
      tooltipText: root.schoolMode ? "School Mode" : "Free Time · " + (root.modeService ? root.modeService.countdownText : "")
      active: root.opened || root.schoolMode
      onPressed: root.togglePanel()
    }
    Text {
      objectName: "freeTimeCountdown"
      visible: root.showCountdown
      anchors.verticalCenter: parent.verticalCenter
      text: root.showCountdown ? root.modeService.countdownText : ""
      color: root.bar ? root.bar.foreground : Color.foreground
      font.family: root.bar ? root.bar.fontFamily : Style.font.family
      font.pixelSize: Style.font.body
      MouseArea { anchors.fill: parent; onClicked: root.togglePanel() }
    }
  }
}
