import QtQuick

QtObject {
  property bool printErrors: false
  property string path: ""
  property bool watchChanges: false
  signal fileChanged()
  signal loaded()
  signal loadFailed()
  function text() { return "" }
  function reload() { loadFailed() }
}
