# School / Free Time

Scheduled school mode, approved apps in both School and Free Time, and password-protected mode changes. This is the standalone School Mode plugin, with its own parent settings panel.

A community plugin for **Omarchy Quattro with the Quickshell plugin system**. It works on a regular Omarchy installation; an Omarchy Kids ISO or fork is not required. The plugin ID is `io.github.peterholko.school-mode`.

## Install

Run these commands in the intended user's Omarchy desktop session:

```bash
omarchy plugin add https://github.com/peterholko/omarchy-school-mode --enable
omarchy bar put io.github.peterholko.school-mode --section right
```

### Set up the background service

Adding the shell plugin alone does not install or authorize a privileged service. Review `setup` and `service/`, then run this in a terminal. Replace `CHILD_USERNAME` with the local account to enroll (for example, `linnea`):

```bash
omarchy pkg add python
sudo "$HOME/.config/omarchy/plugins/io.github.peterholko.school-mode/setup" --user CHILD_USERNAME
```

Setup asks for a new **controls parent password** of at least eight characters, or preserves the password if the community controls service is already installed. School Mode uses `omarchy-kids-controls.service`, which can also host other community controls modules. The separate `peterholko.screen-time` plugin uses its own service and parent authentication. Setup copies only this repository's local, reviewed payload; it does not download code. Installing another module preserves existing settings and enrollments. Use matching service releases; unknown files or locally modified installed service files stop setup. Do not use this older service payload to downgrade a newer shared service installed by a game or another controls plugin.

Only the named account is enrolled. Root owns the password hash, schedules, budgets and reward checks. The UI sends passwords over stdin, and the local service authenticates callers by their Unix socket peer credentials. It rate limits failed parent-password attempts. The controls password is separate from the login, administrator and disk passwords.

These are desktop controls for a cooperative family setup. An account that retains administrator access can disable the service, and user-controlled shell plugins are not an application sandbox. This installer does not convert or demote OS accounts. It refuses to enroll an account already configured for the original Omarchy Kids backend, to prevent two services enforcing different policies.

### Enable the approved desktop

In the enrolled user's desktop, run the following **without sudo**. This permits the plugin to hide the stock launcher and route `Super+Space` and `Super+Alt+Space` to the approved app list in both modes. School Mode disables the standard app-launch shortcuts, quiets notifications and parks existing windows. Free Time restores those windows and the previous notification preference while retaining the approved launcher and child shortcuts; windows are not closed.

```bash
python3 -I "$HOME/.config/omarchy/plugins/io.github.peterholko.school-mode/school-desktop.py" enable
```

Click the book/sun widget to enter School Mode or request Free Time. Free Time and changes to the school schedule or school app list require the controls parent password; the password field displays checking feedback. The settings include optional school access to Number Grove, Paw Post Typing and Pawberry Pet Hotel when their desktop launchers are installed. Other school desktop IDs can be configured with the client’s `config patch` command.

Free Time restores the existing [school and creativity app policy](docs/free-time-apps.md), plus the three learning games. It does not expose every installed app. The policy matches exact desktop IDs; Discord, social/AI apps, supervision-only apps and unknown newly installed apps stay outside the launcher and its search. The default Omarchy menu's Community/Discord and app-install actions are not part of either child menu. Both retain Theme and Background under Style. Only installed apps appear; this update installs no applications.

There is one browser profile. This plugin does not filter websites; use a separate DNS/browser policy if needed. Free Time restores the approved browser, Files, Omawrite, Obsidian, Cliamp, Google Maps, Khan Academy and Wikipedia shortcuts through the same app checks as the launcher. As in the original child profile, `Super+Return` remains available in Free Time for parent maintenance. The filtered launcher and standard shortcut changes do not prevent custom shortcuts, terminal commands or manually started applications, and do not terminate existing processes.

The desktop helper journals recovery before applying changes and changes only its own `disabledPlugins` entry in `~/.config/omarchy/shell.json`. Other bar and shell settings are preserved. It keeps a first-use backup under `~/.local/state/omarchy-community-school-mode/`. Custom `XDG_CONFIG_HOME` and `XDG_STATE_HOME` are respected by the helper. Run `school-desktop.py disable` before disabling or removing the plugin; this also revokes desktop consent.

### Manage enrollment and password

```bash
sudo omarchy-kids-controls password
sudo omarchy-kids-controls disable school --user CHILD_USERNAME
sudo omarchy-kids-controls enable school --user CHILD_USERNAME
```

## Optional Screen Time connection

School Mode works independently. To pause a free-time budget during school hours, install [Screen Time](https://github.com/peterholko/omarchy-screen-time-platform) separately. In its parent controls, open **School Mode**, enable **Connect to the separate School Mode plugin**, and save with the parent password or enabled PIN. The connection starts off.

When connected, active School Mode pauses Screen Time's free-time budget and game rewards. Free Time resumes the remaining budget. Bedtime and other blocked periods still apply in Limits mode, and explicit parent locks still apply in both Screen Time modes. If School Mode's service is unavailable, normal screen-time rules apply.

Keep using this plugin's parent panel for the school schedule, application whitelist and password-protected Free Time. The plugins remain separately installable, with separate settings panels; installing Screen Time does not install or replace School Mode.

If you already have a newer `omarchy-kids-controls.service` from a compatible community game or controls plugin, use its installed payload instead of this repository's older service setup:

```bash
sudo omarchy-kids-controls install --module school --user CHILD_USERNAME
```

That service already includes the School Mode code; this activates and enrolls the school module while retaining its version, other modules and settings. The original Omarchy Kids backend is a different installation and is not adopted by this command.

### Service paths and dependencies

The shared service uses Python 3's standard library, systemd/logind and Omarchy's shell/lock/notification commands. School desktop effects also use Bash 5, Hyprland's Lua IPC, jq and flock, supplied by Omarchy. No pip packages, network services or API keys are needed.

- Code: `/usr/lib/omarchy-kids-controls/`
- Commands: `/usr/bin/omarchy-kids-controls` and `omarchy-kids-controls-{time,school,grove}-client`
- Unit: `/etc/systemd/system/omarchy-kids-controls.service`
- Private configuration and password: `/etc/omarchy-kids-controls/`
- Private service state and per-user read-only status: `/var/lib/omarchy-kids-controls/`
- Local socket: `/run/omarchy-kids-controls/sock`

## Update

```bash
omarchy plugin update io.github.peterholko.school-mode --yes
omarchy restart shell
python3 -I "$HOME/.config/omarchy/plugins/io.github.peterholko.school-mode/school-desktop.py" enable
```

Version 1.1.0 restores the Free Time app policy that was omitted from the standalone export. Returning from School Mode keeps the approved launcher and child shortcuts active, restores parked windows and notifications, and preserves the existing school app list. Earlier desktop recovery journals are retained and upgraded, so disabling desktop controls still restores the original menu and bindings. The final command above applies the restored policy in the current desktop session.

The app-library compatibility fix from 1.0.1 is included: when the shell does not supply an app library to community menus, School Mode loads the matching implementation from the installed Omarchy. Both library paths refresh as apps, school approvals or modes change.

This updates the launcher and user-session helpers; it needs no privileged service setup. The saved school approvals, parent password, schedules and Screen Time integration are retained. For future service changes, review the payload before updating the root-owned copy explicitly. Only use the following command if this standalone service is the installed version; a newer shared service from a game must use its matching setup instead:

```bash
sudo "$HOME/.config/omarchy/plugins/io.github.peterholko.school-mode/setup" --user CHILD_USERNAME --upgrade
```

Updating the user-owned shell checkout never silently replaces the installed privileged service.

## Remove

First restore the desktop **in each enrolled user's active session**, without sudo:

```bash
python3 -I "$HOME/.config/omarchy/plugins/io.github.peterholko.school-mode/school-desktop.py" disable
```

Disable this module's enrollments and remove its service installation before removing the shell plugin:

```bash
sudo omarchy-kids-controls remove school
omarchy plugin remove io.github.peterholko.school-mode
```

If the other module is installed, its shared service, password and settings remain. Removing the last module stops and removes the service, unit and owned command wrappers. Configuration, password and history are retained for a deliberate reinstall; inspect `/etc/omarchy-kids-controls/` and `/var/lib/omarchy-kids-controls/` before deleting that data yourself. Modified or unexpected installed files stop automatic removal for review.

## License and source

MIT. See [LICENSE](LICENSE) and [ATTRIBUTION.md](ATTRIBUTION.md) for retained copyright notices and asset provenance. [SOURCE.json](SOURCE.json) records the source revision and reproducible exporter in [Omarchy Kids](https://github.com/peterholko/omarchy-kids).

## Validation

```bash
omarchy plugin validate .
python3 -m unittest discover -s tests -v
```

The local tests require PySide6, Bash and jq. They run the actual menu adapter in Qt with fixture desktop entries and verify desktop transitions, recovery, and shortcut commands without changing a running desktop. The upstream manifest validator is also used. Full desktop behavior, systemd installation and removal require validation on an actual Omarchy laptop. There are no GitHub Actions workflows in this repository.
