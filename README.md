# School Mode has moved into School & Screen Time

School Mode and Screen Time now form **one plugin with one parent control panel**, including Math Time. New installations should use [School & Screen Time](https://github.com/peterholko/omarchy-screen-time).

For an existing installation, follow the [migration instructions](https://github.com/peterholko/omarchy-screen-time#move-from-the-old-separate-school-mode-plugin). Restore the desktop with this old plugin and disable its UI before enabling the combined version. Upgrade the shared service using the new plugin's `setup --upgrade`; existing schedules, budgets, passwords, history and enrollment choices are retained. Do not remove the old service module or its saved state to migrate.

This repository keeps the legacy plugin available for existing users. The documentation below describes that older separate plugin.

---

# School / Free Time

Scheduled school mode, an app allowlist, and password-protected free time.

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

Setup asks for a new **controls parent password** of at least eight characters. Screen Time and School Mode share this password and the `omarchy-kids-controls.service` service. Setup copies only this repository's local, reviewed payload; it does not download code. Installing the second plugin preserves the first plugin's settings and enrollments. Use matching plugin releases; mismatched service versions require an explicit `--upgrade`, and unknown files or locally modified installed service files stop setup.

Only the named account is enrolled. Root owns the password hash, schedules, budgets and reward checks. The UI sends passwords over stdin, and the local service authenticates callers by their Unix socket peer credentials. It rate limits failed parent-password attempts. The controls password is separate from the login, administrator and disk passwords.

These are desktop controls for a cooperative family setup. An account that retains administrator access can disable the service, and user-controlled shell plugins are not an application sandbox. This installer does not convert or demote OS accounts. It refuses to enroll an account already configured for the original Omarchy Kids backend, to prevent two services enforcing different policies.

### Allow the temporary school desktop changes

In the enrolled user's desktop, run the following **without sudo**. This explicitly permits School Mode to temporarily hide the stock launcher, route `Super+Space` and `Super+Alt+Space` to the school app list, disable the standard Omarchy app-launch shortcuts, quiet notifications and park existing windows. Free Time restores the previous state; windows are not closed.

```bash
python3 -I "$HOME/.config/omarchy/plugins/io.github.peterholko.school-mode/school-desktop.py" enable
```

Click the book/sun widget to enter School Mode or request Free Time. Free Time and changes to the schedule or allowed apps require the controls parent password; the password field displays checking feedback. The settings include optional access to Number Grove, Paw Post Typing and Pawberry Pet Hotel when their desktop launchers are installed. Other desktop IDs can be configured with the client’s `config patch` command.

There is one browser profile. This plugin does not filter websites; use a separate DNS/browser policy if needed. The filtered launcher and standard shortcut changes do not prevent custom shortcuts, terminal commands or manually started applications.

The desktop helper journals recovery before applying changes and changes only its own `disabledPlugins` entry in `~/.config/omarchy/shell.json`. Other bar and shell settings are preserved. It keeps a first-use backup under `~/.local/state/omarchy-community-school-mode/`. Custom `XDG_CONFIG_HOME` and `XDG_STATE_HOME` are respected by the helper. Run `school-desktop.py disable` before disabling or removing the plugin; this also revokes desktop consent.

### Manage enrollment and password

```bash
sudo omarchy-kids-controls password
sudo omarchy-kids-controls disable school --user CHILD_USERNAME
sudo omarchy-kids-controls enable school --user CHILD_USERNAME
```

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
omarchy plugin update io.github.peterholko.school-mode
```

Review any service changes, then update the root-owned copy explicitly:

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
```

These packages are checked with the upstream manifest validator and local source tests. Full desktop enforcement, systemd installation and removal require validation on an actual Omarchy laptop. There are no GitHub Actions workflows in this repository.
