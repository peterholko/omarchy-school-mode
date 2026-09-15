import QtQuick
import Quickshell
QtObject {
  id: root
  property var command: []
  property bool running: false
  property bool stdinEnabled: false
  property var stdout: null
  signal started()
  signal exited(int code)
  function write(value) { Quickshell.writes = Quickshell.writes.concat([value]) }
  onRunningChanged: {
    if (!running) return
    Quickshell.execDetached(command)
    Qt.callLater(function() {
      root.started()
      if (root.stdout) root.stdout.streamFinished()
      root.running = false
      root.exited(0)
    })
  }
}
