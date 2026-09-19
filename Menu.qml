import Quickshell
import QtQuick
import "Allowlist.js" as Allowlist
import "FreeTimeApps.js" as FreeTimeApps
import "SchoolBrowser.js" as SchoolBrowser

// The menu of a child install, after elgevan's omarchy-kids-menu: the menu
// implementation shipped by the running Omarchy, loaded here and pointed at
// a filtered view of the installed apps. School uses its saved parent list;
// Free Time uses the family's existing school-and-creativity app policy.
Loader {
  id: root

  property string omarchyPath: ""
  property var shell: null
  property var manifest: null
  // Omarchy injects the matching service into menu entry points that expose
  // this property. Use it directly so a cached shell lookup cannot strand the
  // launcher while the bar is already receiving live School Mode status.
  property var service: null
  property int serviceLookupRevision: 0
  property string pendingPayload: ""
  property bool hasPendingPayload: false
  readonly property bool opened: item ? item.opened === true : false

  readonly property var shellAppLibrary: root.shell && root.shell.appLibrary
    && typeof root.shell.appLibrary.sortedEntries === "function" ? root.shell.appLibrary : null
  readonly property var sourceAppLibrary: root.shellAppLibrary || localAppLibrary.item
  readonly property var lookedUpService: {
    root.serviceLookupRevision
    return root.shell && typeof root.shell.serviceFor === "function"
      ? root.shell.serviceFor("io.github.peterholko.school-mode") : null
  }
  readonly property var modeService: root.service || root.lookedUpService
  readonly property bool schoolMode: root.modeService ? root.modeService.schoolMode === true : false
  // Only a confirmed disabled enrollment restores the unrestricted menu.
  // While status is loading, do not briefly expose the full application set.
  readonly property bool restrictApps: !root.modeService || !root.modeService.connected || root.modeService.schoolEnabled === true
  readonly property var approvedDesktopIds: !root.modeService || !root.modeService.connected || !root.modeService.schoolEnabled ? []
    : (root.schoolMode ? root.modeService.allowedDesktopIds : FreeTimeApps.DESKTOP_IDS)
  readonly property string pluginRoot: decodeURIComponent(Qt.resolvedUrl(".").toString().replace(/^file:\/\//, "")).replace(/\/$/, "")
  readonly property string homeDir: Quickshell.env("HOME")

  asynchronous: false
  source: omarchyPath ? "file://" + omarchyPath + "/shell/plugins/menu/Menu.qml" : ""

  // Older hosts supply only serviceFor(). A lookup can initially return null
  // without a later change notification; retry until status is connected.
  Timer {
    interval: 1000
    repeat: true
    running: !root.modeService || !root.modeService.connected
    onTriggered: root.reconnectService()
  }

  function reconnectService() { root.serviceLookupRevision += 1 }

  // When the host does not supply an app library, load the matching installed
  // implementation in this same shell process, preserving its desktop-entry
  // filtering, icons and launch behavior.
  Loader {
    id: localAppLibrary
    active: !root.shellAppLibrary && root.omarchyPath !== ""
    source: active ? "file://" + root.omarchyPath + "/shell/services/AppLibrary.qml" : ""
    onLoaded: item.omarchyPath = root.omarchyPath
  }

  // A provider may already have cached an empty result before the library
  // becomes ready. Refresh that result when the library is first supplied.
  onSourceAppLibraryChanged: Qt.callLater(function() {
    root.configureMenu()
    filteredAppLibrary.appsChanged()
  })

  // The stock menu keeps its behaviour, but sees a filtered, read-only view
  // of DesktopEntries. Neither child mode uninstalls applications.
  QtObject {
    id: filteredAppLibrary
    signal appsChanged()

    function sortedEntries(query) {
      if (!root.sourceAppLibrary) return []
      var rows = root.sourceAppLibrary.sortedEntries(query)
      return root.restrictApps ? Allowlist.filterRows(rows, root.approvedDesktopIds) : rows
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
      if (root.restrictApps && !Allowlist.contains(root.approvedDesktopIds, desktopId)) return
      // With a separate school profile, the browser and every web app open
      // in it; with one profile, the ordinary way.
      if (root.schoolMode && SchoolBrowser.SEPARATE_PROFILE) {
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
      if (!root.restrictApps && root.sourceAppLibrary) {
        root.sourceAppLibrary.remove(desktopId, name)
        return
      }
      Quickshell.execDetached(["omarchy-notification-send", "School / Free Time filters the launcher; app removal is a parent task."])
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
  }

  // Refresh after this binding changes; the service signal can arrive before
  // root.schoolMode has caught up, leaving the previous mode's cached rows.
  onSchoolModeChanged: configureMenu()
  onRestrictAppsChanged: configureMenu()
  onApprovedDesktopIdsChanged: filteredAppLibrary.appsChanged()

  // Both child modes use their curated menu, including search and deep links.
  function normalizedPayload(payloadJson) {
    var raw = payloadJson || "{}"
    if (!root.restrictApps) return raw
    try {
      var payload = JSON.parse(raw)
      if (payload && payload.mode !== "select" && payload.mode !== "input") {
        var route = String(payload.initialMenu || payload.menu || "root")
        var styleRoute = route === "style" || route.indexOf("style.") === 0
        var captureRoute = route === "trigger.capture" || route.indexOf("trigger.capture.") === 0
        if (!styleRoute && !captureRoute) route = "apps"
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
    return launchAllowedApp(JSON.stringify({ desktopId: "chromium", name: "Chromium" }))
  }

  function launchAllowedApp(payloadJson) {
    reconnectService()
    if (!root.modeService || !root.modeService.schoolEnabled) return "inactive"
    var payload = ({})
    try { payload = JSON.parse(payloadJson || "{}") } catch (error) { return "invalid" }
    var desktopId = SchoolBrowser.normalizeDesktopId(payload.desktopId)
    if (!desktopId || !Allowlist.contains(root.approvedDesktopIds, desktopId)) return "blocked"
    if (!filteredAppLibrary.entryFor(desktopId)) return "unavailable"
    // Preserve the two standard shortcut variants after checking the same
    // app approval. No caller-supplied command or arbitrary flags are run.
    var variant = String(payload.variant || "")
    if (variant === "private" && desktopId === "chromium") {
      Quickshell.execDetached(["uwsm-app", "--", "chromium", "--incognito"])
      root.guardAppLaunch()
      return "ok"
    }
    if (variant === "cwd" && desktopId === "org.gnome.Nautilus") {
      Quickshell.execDetached(["omarchy-launch-nautilus-cwd"])
      root.guardAppLaunch()
      return "ok"
    }
    if (variant !== "") return "invalid"
    filteredAppLibrary.launch(desktopId, String(payload.name || desktopId))
    return "ok"
  }

  function configureMenu() {
    if (!item) return
    item.omarchyPath = root.omarchyPath
    item.shell = root.restrictApps || !root.shellAppLibrary ? filteredShell : root.shell
    item.manifest = root.manifest
    if (root.restrictApps && root.pluginRoot) {
      item.defaultMenuPath = root.pluginRoot + (root.schoolMode ? "/school-menu.jsonc" : "/free-time-menu.jsonc")
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
    reconnectService()
    var payload = normalizedPayload(payloadJson)
    if (item) {
      configureMenu()
      item.open(payload)
    } else {
      pendingPayload = payload
      hasPendingPayload = true
    }
    if (!root.modeService || !root.modeService.connected)
      console.warn("School / Free Time launcher status: " + diagnostics())
  }

  function close() {
    pendingPayload = ""
    hasPendingPayload = false
    if (item) item.close()
  }

  function refresh() {
    reconnectService()
    if (!item) return "loading"
    configureMenu()
    return item.refresh()
  }

  function ping() { return item ? item.ping() : "loading" }

  // Read-only IPC: compare the launcher's binding with a fresh host lookup,
  // and distinguish missing status from an empty installed-app provider.
  function diagnostics() {
    function status(value) {
      return {
        available: !!value,
        connected: !!value && value.connected === true,
        enabled: !!value && value.schoolEnabled === true,
        mode: value ? (value.schoolMode ? "school" : "free") : "unavailable"
      }
    }
    var fresh = root.shell && typeof root.shell.serviceFor === "function"
      ? root.shell.serviceFor("io.github.peterholko.school-mode") : null
    var sourceRows = root.sourceAppLibrary ? root.sourceAppLibrary.sortedEntries("") : []
    var visibleRows = filteredAppLibrary.sortedEntries("")
    var cachedApps = null
    if (item && "items" in item) {
      cachedApps = 0
      for (var id in item.items)
        if (item.items[id] && item.items[id].kind === "app") cachedApps += 1
    }
    return JSON.stringify({
      schemaVersion: 1,
      pluginVersion: root.manifest ? String(root.manifest.version || "") : "",
      serviceSource: root.service ? "injected" : (root.lookedUpService ? "shell" : "missing"),
      service: status(root.modeService),
      freshLookup: status(fresh),
      restricted: root.restrictApps,
      approvedApps: root.approvedDesktopIds.length,
      availableApps: sourceRows.length,
      visibleApps: visibleRows.length,
      menuLoaded: !!item,
      cachedApps: cachedApps,
      activeMenu: item && "activeMenu" in item ? item.activeMenu : ""
    })
  }

  onLoaded: configureMenu()
  onOmarchyPathChanged: configureMenu()
  onShellChanged: configureMenu()
  onManifestChanged: configureMenu()
}
