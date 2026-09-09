# The apps a child install shows in school mode: school and creativity
# without the games and the entertainment, by desktop id.
DEFAULT_SCHOOL_APPS = [
    "chromium", "libreoffice-startcenter", "libreoffice-writer", "libreoffice-calc",
    "libreoffice-impress", "libreoffice-draw", "org.gnome.Nautilus", "org.gnome.Evince",
    "imv", "omawrite", "omacalc", "com.github.xournalpp.xournalpp", "obsidian",
    "Khan Academy", "Wikipedia", "io.github.peterholko.math",
]

def sanitize_school_apps(raw):
    if not isinstance(raw, list):
        return list(DEFAULT_SCHOOL_APPS)
    out = []
    for entry in raw[:200]:
        if not isinstance(entry, str):
            continue
        name = entry.strip()
        if name.endswith(".desktop"):
            name = name[:-8]
        if name and len(name) <= 80 and name not in out:
            out.append(name)
    return out
