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
    return JSON.stringify({commands: Quickshell.detachedCommands,
      connected: serviceLoader.item ? serviceLoader.item.connected : false,
      school: serviceLoader.item ? serviceLoader.item.schoolMode : false})
  }
}
