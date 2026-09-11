import QtQuick

Item {
  property string omarchyPath: ""
  property var entries: [
    {id: "chromium", name: "Chromium", icon: "chromium"},
    {id: "org.gnome.Nautilus", name: "Files", icon: "files"},
    {id: "Khan Academy", name: "Khan Academy", icon: "khan"},
    {id: "com.github.PintaProject.Pinta", name: "Pinta", icon: "pinta"},
    {id: "cliamp", name: "Cliamp", icon: "cliamp"},
    {id: "io.github.peterholko.pawberry", name: "Pawberry Pet Hotel", icon: "pawberry"},
    {id: "io.github.peterholko.number-grove", name: "Number Grove", icon: "grove"},
    {id: "io.github.peterholko.paw-post", name: "Paw Post", icon: "post"},
    {id: "steam", name: "Steam", icon: "steam"},
    {id: "Discord", name: "Discord", icon: "discord"},
    {id: "discord", name: "Discord native", icon: "discord"},
    {id: "ChatGPT", name: "ChatGPT", icon: "ai"},
    {id: "YouTube", name: "YouTube", icon: "youtube"},
    {id: "Zoom", name: "Zoom", icon: "zoom"},
    {id: "new-app", name: "Newly installed app", icon: "app"}
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
