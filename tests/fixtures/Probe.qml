import QtQuick
import Quickshell
import "shell/services"

Item {
  id: root
  property bool exposeLibrary: true
  property bool injectService: false
  property bool lookupStartsAvailable: true
  // Some host lookup callbacks do not notify bindings when a service is
  // registered. Mutating this map reproduces that contract without emitting
  // a property change from the facade.
  property var lookupState: ({available: root.lookupStartsAvailable})
  property string pluginPath: ""
  property string installedPath: ""
  AppLibrary { id: sharedLibrary }
  property QtObject mode: QtObject {
    property bool connected: true
    property bool schoolEnabled: true
    property bool schoolMode: true
    property var allowedDesktopIds: ["chromium.desktop", "org.gnome.Nautilus", "Khan Academy"]
    signal allowlistChanged()
    onAllowedDesktopIdsChanged: allowlistChanged()
    function guardAppLaunch() {}
  }
  property QtObject api: QtObject {
    property var appLibrary: root.exposeLibrary ? sharedLibrary : null
    property var pluginRegistry: null
    property var barWidgetRegistry: null
    function serviceFor(id) { return root.lookupState.available ? root.mode : null }
  }
  Loader {
    id: plugin
    source: root.pluginPath ? "file://" + root.pluginPath + "/Menu.qml" : ""
    onLoaded: {
      item.shell = root.api
      item.omarchyPath = root.installedPath
      item.manifest = {id: "io.github.peterholko.school-mode"}
      if (root.injectService) item.service = root.mode
    }
  }

  function invoke(action: string): string {
    var menu = plugin.item.item
    var library = plugin.item.sourceAppLibrary
    if (action === "open") plugin.item.open('{"menu":"root"}')
    else if (action === "refresh") plugin.item.refresh()
    else if (action === "publish-service") root.lookupState.available = true
    else if (action === "diagnostics") return plugin.item.diagnostics()
    else if (action === "revoke") {
      mode.allowedDesktopIds = ["Khan Academy"]
      menu.shell.appLibrary.launch("chromium", "Chromium")
    } else if (action === "launch") menu.shell.appLibrary.launch("Khan Academy", "Khan Academy")
    else if (action === "remove-app") library.entries = library.entries.filter(function(entry) { return entry.id !== "org.gnome.Nautilus" })
    else if (action === "add-app") {
      mode.allowedDesktopIds = mode.allowedDesktopIds.concat(["omawrite"])
      library.entries = library.entries.concat([{id: "omawrite", name: "Omawrite", icon: "write"}])
    } else if (action === "free") mode.schoolMode = false
    else if (action === "school") mode.schoolMode = true
    else if (action === "remove-free") menu.shell.appLibrary.remove("steam", "Steam")
    else if (action === "launch-discord") menu.shell.appLibrary.launch("Discord", "Discord")
    else if (action === "launch-pinta") menu.shell.appLibrary.launch("com.github.PintaProject.Pinta", "Pinta")
    else if (action === "discord-shortcut") return JSON.stringify({verdict: plugin.item.launchAllowedApp('{"desktopId":"Discord"}')})
    else if (action === "pinta-shortcut") return JSON.stringify({verdict: plugin.item.launchAllowedApp('{"desktopId":"com.github.PintaProject.Pinta"}')})
    else if (action === "private-shortcut") return JSON.stringify({verdict: plugin.item.launchAllowedApp('{"desktopId":"chromium","variant":"private"}'), commands: Quickshell.detachedCommands})
    else if (action === "cwd-shortcut") return JSON.stringify({verdict: plugin.item.launchAllowedApp('{"desktopId":"org.gnome.Nautilus","variant":"cwd"}'), commands: Quickshell.detachedCommands})
    else if (action === "invalid-variant") return JSON.stringify({verdict: plugin.item.launchAllowedApp('{"desktopId":"chromium","variant":"shell"}'), commands: Quickshell.detachedCommands})
    else if (action === "community-route") plugin.item.open('{"menu":"learn.community"}')
    else if (action === "disabled") mode.schoolEnabled = false
    else if (action === "loading") { mode.connected = false; mode.schoolEnabled = false; mode.schoolMode = false }
    else if (action === "disconnect") mode.connected = false
    else if (action === "search") { menu.query = "files"; menu.mergeApps() }
    else if (action === "empty") mode.allowedDesktopIds = []
    else if (action === "supply-library") root.exposeLibrary = true
    var rows = menu.rows
    return JSON.stringify({
      ids: rows.map(function(row) { return row.entry.id }),
      names: rows.map(function(row) { return menu.shell.appLibrary.entryName(row.entry) }),
      icons: rows.map(function(row) { return menu.shell.appLibrary.iconSource(row.entry.icon) }),
      launches: library ? library.launches : [],
      removals: library ? library.removals : [],
      usesSharedLibrary: plugin.item.sourceAppLibrary === sharedLibrary,
      payload: menu.payload,
      menuPath: menu.defaultMenuPath
    })
  }
}
