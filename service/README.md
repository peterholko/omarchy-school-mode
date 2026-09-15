# Shared controls service 4.2.0

This payload is shipped by the standalone School / Free Time plugin. It upgrades the 4.0.0 practice-only service used by Pawberry Pet Hotel, Number Grove and Paw Post without changing their game protocols, completed work, limits or collections. Game endpoints still return zero time and cannot register or enable rewards.

Explicit School setup installs the root-owned code, per-service PAM gates and School enrollment. It removes only the named child's prior Screen Time enrollments, retaining the former settings and history. Fresh game setup does not enroll School Mode or a time module. Existing modules and parent passwords are retained. Setup never downloads code and rejects file collisions, local modifications and downgrades.

The School service stores each parent-granted allowance's deadline and next scheduled School transition in private per-user state. The first event wins, even across reboot. An expired allowance remains parent-locked until authenticated return to School Mode. Normal manual locks before expiry use the original PAM policy. The PAM helper uses a fixed socket, validates the calling identity and drops root before checking a parent's typed password. Root administrative recovery remains available.

See the repository [README](../README.md) for installation, updating, PAM recovery and removal. Run `python3 -m unittest discover -s tests -v` from this checkout for local protocol, persistence, setup and QML regressions. Real Linux PAM/session locking requires a manual Omarchy check; no CI, ISO or VM runs are involved.

The School module includes optional Chrome/Chromium website filtering. Separate domain, policy, installer and native-messaging modules keep it independent of the Free Time timer. Setup prepares a locally signed browser companion; only a parent's Websites setting activates it. See [website integration](../docs/websites.md) for owned files, machine-wide scope, transport and local validation.
