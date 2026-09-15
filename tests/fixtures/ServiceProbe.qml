import QtQuick
import Quickshell

Item {
  id: root
  property string pluginPath: ""
  Loader {
    id: serviceLoader
    source: root.pluginPath ? "file://" + root.pluginPath + "/Service.qml" : ""
  }
  function invoke(action: string): string {
    if (action === "stop") serviceLoader.active = false
    else if (action === "start") serviceLoader.active = true
    else if (action === "school" || action === "free")
      serviceLoader.item.loadStatus(JSON.stringify({schemaVersion: 1, enabled: true, mode: action, schoolApps: ["chromium"]}))
    else if (action === "disabled")
      serviceLoader.item.loadStatus('{"schemaVersion":1,"enabled":false}')
    else if (action === "invalid")
      serviceLoader.item.loadStatus('{"schemaVersion":99,"enabled":false}')
    else if (action === "timer" || action === "same-timer")
      serviceLoader.item.loadStatus('{"schemaVersion":1,"enabled":true,"mode":"free","updatedAt":100,"freeTimeTimerVersion":1,"freeTimeReady":true,"freeTimeRemainingSeconds":1800}')
    else if (action === "elapse") {
      serviceLoader.item.countdownReadAt -= 3000
      serviceLoader.item.countdownNow = Date.now()
    }
    return JSON.stringify({commands: Quickshell.detachedCommands,
      connected: serviceLoader.item ? serviceLoader.item.connected : false,
      school: serviceLoader.item ? serviceLoader.item.schoolMode : false,
      countdown: serviceLoader.item ? serviceLoader.item.countdownText : ""})
  }
}
