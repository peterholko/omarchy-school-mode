import QtQuick

// The native menu caches its Apps provider, then updates it on appsChanged.
Item {
  id: root
  property string omarchyPath: ""
  property var shell: null
  property var manifest: null
  property string defaultMenuPath: ""
  property string userMenuPath: ""
  property var rows: []
  property bool opened: false
  property string payload: ""
  property string query: ""

  function mergeApps() { rows = shell && shell.appLibrary ? shell.appLibrary.sortedEntries(query) : [] }
  function refresh() { if (opened) mergeApps(); return "ok" }
  function open(value) { payload = value; opened = true; mergeApps() }
  function close() { opened = false }
  function ping() { return "ok" }

  Connections {
    target: root.shell ? root.shell.appLibrary : null
    function onAppsChanged() { if (root.opened) root.mergeApps() }
  }
}
