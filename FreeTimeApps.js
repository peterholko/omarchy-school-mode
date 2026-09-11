// The existing family app policy, recovered from kids-apps-themes.md:
// school and creativity apps, plus the three subsequently approved games.
// Match desktop IDs exactly; a similar name or category is not approval.
var DESKTOP_IDS = [
  "chromium",
  "libreoffice-startcenter", "libreoffice-writer", "libreoffice-calc",
  "libreoffice-impress", "libreoffice-draw", "libreoffice-math", "libreoffice-base",
  "org.gnome.Nautilus", "org.gnome.Evince", "imv", "mpv",
  "omawrite", "omacalc", "pinta", "com.github.PintaProject.Pinta",
  "com.github.xournalpp.xournalpp", "aether", "li.oever.aether",
  "obsidian", "org.kde.kdenlive", "cliamp", "Google Maps",
  "Khan Academy", "Wikipedia",
  "io.github.peterholko.pawberry", "io.github.peterholko.number-grove", "io.github.peterholko.paw-post"
]

if (typeof module !== "undefined") module.exports = { DESKTOP_IDS: DESKTOP_IDS }
