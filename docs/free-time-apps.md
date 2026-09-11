# Free Time approved apps

This restores the family app policy recorded before the standalone plugin split. Free Time uses the exact desktop IDs in [FreeTimeApps.js](../FreeTimeApps.js); it does not infer approval from a display name, category, or installation date. School Mode continues to use its existing parent-managed `school_apps` list. Changing school approvals does not replace the Free Time policy.

| Approved apps | Desktop IDs |
| --- | --- |
| Chromium | `chromium` |
| LibreOffice | `libreoffice-startcenter`, `libreoffice-writer`, `libreoffice-calc`, `libreoffice-impress`, `libreoffice-draw`, `libreoffice-math`, `libreoffice-base` |
| Files and document viewer | `org.gnome.Nautilus`, `org.gnome.Evince` |
| Image and media viewers | `imv`, `mpv` |
| Omawrite and Omacalc | `omawrite`, `omacalc` |
| Pinta | `pinta`, `com.github.PintaProject.Pinta` |
| Xournal++ | `com.github.xournalpp.xournalpp` |
| Aether | `aether`, `li.oever.aether` |
| Obsidian | `obsidian` |
| Kdenlive | `org.kde.kdenlive` |
| Cliamp | `cliamp` |
| Google Maps | `Google Maps` |
| Khan Academy and Wikipedia | `Khan Academy`, `Wikipedia` |
| Subsequently added learning games | `io.github.peterholko.pawberry`, `io.github.peterholko.number-grove`, `io.github.peterholko.paw-post` |

The original supervision-only group stays outside ordinary Free Time: the unrestricted YouTube shortcut, Zoom, LocalSend, Moonlight, general games, OBS Studio and WhatsApp. Discord, X, ChatGPT/Grok and other AI apps, Basecamp, HEY, Google Messages, Docker, administrative tools, terminals and developer tools are also excluded from the child launcher. The three learning games above are the later approved additions. Newly installed apps do not gain Free Time access automatically.

The recorded policy also retains the Free Time `Super+Return` terminal shortcut for parent maintenance. These are launcher and standard-shortcut controls; they do not change program permissions, inspect browser activity or block manually launched applications. There is no new Free Time settings editor in this restoration.

Source: the existing [app-policy decisions](https://github.com/peterholko/omarchy-kids/blob/0228567a/plans/kids-apps-themes.md#decisions), including the child launcher entries and shortcuts. The source repository is retained as a reference; this implementation lives in the standalone School / Free Time plugin.
