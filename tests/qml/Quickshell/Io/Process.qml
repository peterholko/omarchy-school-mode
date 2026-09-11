import QtQuick
import Quickshell

QtObject {
  id: root
  property var command: []
  property bool running: false
  property var stdout: null
  signal exited(int code)
  onRunningChanged: {
    if (!running) return
    Quickshell.execDetached(command)
    Qt.callLater(function() {
      root.running = false
      root.exited(0)
    })
  }
}
