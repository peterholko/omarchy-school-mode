import QtQuick

Item {
  property string omarchyPath: ""
  property var entries: [
    {id: "chromium", name: "Chromium", icon: "chromium"},
    {id: "org.gnome.Nautilus", name: "Files", icon: "files"},
    {id: "Khan Academy", name: "Khan Academy", icon: "khan"},
    {id: "steam", name: "Steam", icon: "steam"}
  ]
  property var launches: []
  property var removals: []
  signal appsChanged()
  onEntriesChanged: appsChanged()

  function sortedEntries(query) {
    return entries.filter(function(entry) {
      return entry.name.toLowerCase().indexOf(query.toLowerCase()) >= 0
    }).map(function(entry) { return {entry: entry} })
  }
  function entryName(entry) { return entry.name }
  function entrySubtext(entry) { return "Installed app" }
  function iconSource(icon) { return "image://icon/" + icon }
  function refreshIcons() {}
  function launch(id, name) { launches = launches.concat([id]) }
  function remove(id, name) { removals = removals.concat([id]) }
}
