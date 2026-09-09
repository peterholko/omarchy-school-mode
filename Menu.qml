import Quickshell
import QtQuick
import "Allowlist.js" as Allowlist
import "SchoolBrowser.js" as SchoolBrowser

// The menu of a child install, after elgevan's omarchy-kids-menu: the menu
// implementation shipped by the running Omarchy, loaded here and pointed at
// a filtered view of the installed apps while school mode is on. In free
// time it is the stock menu with the stock definitions.
Loader {
  id: root

  property string omarchyPath: ""
  property var shell: null
  property var manifest: null
  property string pendingPayload: ""
  property bool hasPendingPayload: false

  readonly property var sourceAppLibrary: shell ? shell.appLibrary : null
  readonly property var modeService: shell && typeof shell.serviceFor === "function"
    ? shell.serviceFor("io.github.peterholko.school-mode")
    : null
  readonly property bool schoolMode: root.modeService ? root.modeService.schoolMode === true : false
  readonly property string pluginRoot: decodeURIComponent(Qt.resolvedUrl(".").toString().replace(/^file:\/\//, "")).replace(/\/$/, "")
  readonly property string homeDir: Quickshell.env("HOME")

  asynchronous: false
  source: omarchyPath ? "file://" + omarchyPath + "/shell/plugins/menu/Menu.qml" : ""

  // The stock menu keeps its behaviour, but sees a filtered, read-only view
  // of DesktopEntries. remove() is a no-op: school mode uninstalls nothing.
  QtObject {
    id: filteredAppLibrary
    signal appsChanged()

    function sortedEntries(query) {
      if (!root.sourceAppLibrary || !root.modeService) return []
      return Allowlist.filterRows(root.sourceAppLibrary.sortedEntries(query), root.modeService.allowedDesktopIds)
    }

    function entryFor(desktopId) {
      if (!root.sourceAppLibrary) return null
      var expected = SchoolBrowser.normalizeDesktopId(desktopId)
      var rows = root.sourceAppLibrary.sortedEntries("")
      for (var i = 0; i < rows.length; i++) {
        var entry = rows[i] ? rows[i].entry : null
        if (entry && SchoolBrowser.normalizeDesktopId(entry.id) === expected) return entry
      }
      return null
    }

    function entryName(entry) { return root.sourceAppLibrary ? root.sourceAppLibrary.entryName(entry) : "" }
    function entrySubtext(entry) { return root.sourceAppLibrary ? root.sourceAppLibrary.entrySubtext(entry) : "" }
    function iconSource(icon) { return root.sourceAppLibrary ? root.sourceAppLibrary.iconSource(icon) : "" }
    function isHiddenEntry(entry) { return root.sourceAppLibrary && typeof root.sourceAppLibrary.isHiddenEntry === "function" ? root.sourceAppLibrary.isHiddenEntry(entry) : false }

    function launch(desktopId, name) {
      if (!root.sourceAppLibrary) return
      // With a separate school profile, the browser and every web app open
      // in it; with one profile, the ordinary way.
      if (SchoolBrowser.SEPARATE_PROFILE) {
        var entry = filteredAppLibrary.entryFor(desktopId)
        var webAppUrl = SchoolBrowser.webAppUrl(entry ? entry.command : [], entry ? entry.execString : "")
        if (SchoolBrowser.isBrowser(desktopId) || webAppUrl) {
          if (typeof root.sourceAppLibrary.beginLaunchFeedback === "function")
            root.sourceAppLibrary.beginLaunchFeedback(name)
          Quickshell.execDetached(SchoolBrowser.launchCommand(root.homeDir, webAppUrl))
          root.guardAppLaunch()
          return
        }
      }
      root.sourceAppLibrary.launch(desktopId, name)
      root.guardAppLaunch()
    }

    function refreshIcons() { if (root.sourceAppLibrary) root.sourceAppLibrary.refreshIcons() }

    function remove(desktopId, name) {
      Quickshell.execDetached(["omarchy-notification-send", "School mode only filters the menu; a parent changes the list in the School / Free Time settings."])
    }
  }

  // The stock menu reaches the shell for more than apps; everything but the
  // app library passes straight through.
  QtObject {
    id: filteredShell
    property var appLibrary: filteredAppLibrary
    property var pluginRegistry: root.shell ? root.shell.pluginRegistry : null
    property var barWidgetRegistry: root.shell ? root.shell.barWidgetRegistry : null
    property string omarchyPath: root.omarchyPath
    function serviceFor(id) { return root.shell ? root.shell.serviceFor(id) : null }
    function summon(id, payload) { return root.shell ? root.shell.summon(id, payload) : false }
    function hide(id) { return root.shell ? root.shell.hide(id) : false }
    function toggle(id, payload) { return root.shell ? root.shell.toggle(id, payload) : false }
    function isPluginOpen(id) { return root.shell ? root.shell.isPluginOpen(id) : false }
    function callIfLoaded(id, method, arg) { return root.shell ? root.shell.callIfLoaded(id, method, arg) : "unknown" }
  }

  Connections {
    target: root.sourceAppLibrary
    function onAppsChanged() { filteredAppLibrary.appsChanged() }
  }

  Connections {
    target: root.modeService
    function onAllowlistChanged() { filteredAppLibrary.appsChanged() }
    function onSchoolModeChanged() { root.configureMenu() }
  }

  // In school mode every route but Style lands on the apps list.
  function normalizedPayload(payloadJson) {
    var raw = payloadJson || "{}"
    if (!root.schoolMode) return raw
    try {
      var payload = JSON.parse(raw)
      if (payload && payload.mode !== "select" && payload.mode !== "input") {
        var route = String(payload.initialMenu || payload.menu || "root")
        if (route !== "style" && route.indexOf("style.") !== 0) route = "apps"
        if (payload.initialMenu !== undefined) payload.initialMenu = route
        else payload.menu = route
        return JSON.stringify(payload)
      }
    } catch (error) {
    }
    return raw
  }

  function guardAppLaunch() {
    if (root.modeService && typeof root.modeService.guardAppLaunch === "function")
      root.modeService.guardAppLaunch()
  }

  function launchSchoolBrowser() {
    if (!root.schoolMode || !SchoolBrowser.SEPARATE_PROFILE) {
      Quickshell.execDetached(["omarchy-launch-browser"])
      return root.schoolMode ? "ok" : "free"
    }
    Quickshell.execDetached(SchoolBrowser.launchCommand(root.homeDir, ""))
    root.guardAppLaunch()
    return "ok"
  }

  function launchAllowedApp(payloadJson) {
    if (!root.schoolMode || !root.modeService) return "inactive"
    var payload = ({})
    try { payload = JSON.parse(payloadJson || "{}") } catch (error) { return "invalid" }
    var desktopId = SchoolBrowser.normalizeDesktopId(payload.desktopId)
    if (!desktopId || !root.modeService.isAllowed(desktopId)) return "blocked"
    filteredAppLibrary.launch(desktopId, String(payload.name || desktopId))
    return "ok"
  }

  function configureMenu() {
    if (!item) return
    item.omarchyPath = root.omarchyPath
    item.shell = root.schoolMode ? filteredShell : root.shell
    item.manifest = root.manifest
    if (root.schoolMode && root.pluginRoot) {
      item.defaultMenuPath = root.pluginRoot + "/school-menu.jsonc"
      item.userMenuPath = root.pluginRoot + "/empty-menu.jsonc"
      item.refresh()
    } else if (root.omarchyPath) {
      item.defaultMenuPath = root.omarchyPath + "/default/omarchy/omarchy-menu.jsonc"
      item.userMenuPath = Quickshell.env("HOME") + "/.config/omarchy/extensions/omarchy-menu.jsonc"
      item.refresh()
    }
    if (root.hasPendingPayload) {
      var payload = root.pendingPayload
      root.pendingPayload = ""
      root.hasPendingPayload = false
      item.open(payload)
    }
  }

  function open(payloadJson) {
    var payload = normalizedPayload(payloadJson)
    if (item) {
      configureMenu()
      item.open(payload)
    } else {
      pendingPayload = payload
      hasPendingPayload = true
    }
  }

  function close() {
    pendingPayload = ""
    hasPendingPayload = false
    if (item) item.close()
  }

  function refresh() {
    if (!item) return "loading"
    configureMenu()
    return item.refresh()
  }

  function ping() { return item ? item.ping() : "loading" }

  onLoaded: configureMenu()
  onOmarchyPathChanged: configureMenu()
  onShellChanged: configureMenu()
  onManifestChanged: configureMenu()
}
