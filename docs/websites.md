# School website integration

The parent profile stores `websites_enabled` (default false) and `school_blocked_domains` (default empty). The existing authenticated `school config patch` route validates the complete patch before saving it. Old profiles acquire the disabled default. Domain lists accept DNS hostnames and an optional leading `*.`; matching always includes the host and its subdomains. Arbitrary browser URL patterns, paths, ports and IP addresses are rejected. At most 100 distinct domains may be configured across enrolled profiles.

## Enforcement and scope

The root service computes the union of enabled domain lists whose enrolled accounts are in School Mode. It publishes that list through Chrome/Chromium's managed `URLBlocklist` and through a locally installed Manifest V3 companion. The browser's policies are machine-wide, including adult accounts; they are not per-profile Linux policies. This is intended for a dedicated child laptop.

The companion applies dynamic request-blocking rules, including subdomains and embedded requests. On receipt of a new list it checks existing regular tabs and replaces matching top-level pages with its local notice, stopping those pages. It rechecks a tab immediately before navigation to avoid replacing a tab that has meanwhile moved to school work. The original URL stays in the local notice fragment for an explicit retry after Free Time. It is never sent to the native bridge or service. Already loaded content embedded in an unrelated page is not removed; future requests to the blocked host are denied. Existing Incognito/Guest content is outside this tab handling. The URL policy still restricts new navigations there.

The extension's native connection polls every two seconds. The service checks schedules on its normal tick, including reboot restoration and expiry-parent-unlock transitions. Browser receipt is informational: it confirms the latest generation was acknowledged by connected companion instances for the current account, not that every possible browser/profile is protected. The interface reports missing setup, pending browser startup, stale companion versions, policy conflicts and application errors instead of treating a saved list as proof of enforcement.

Transient service restarts retain the last browser request rules. Free Time clears only this extension's rules and removes this plugin's `URLBlocklist`. Disabling Websites or removing the School module removes its force-install/managed flag; the companion clears its persistent rules on managed-policy removal. Existing administrator policies and other extensions are never modified. Conflicts with `URLBlocklist`, `URLAllowlist`, `ExtensionSettings` or `ExtensionInstallForcelist` in other managed/recommended JSON files stop activation, since Chrome does not define precedence between files setting the same policy. Conflicts introduced afterward are reported; Free Time still removes our old School block list.

## Owned integration

Setup prepares these artifacts, but publishes no browser restrictions until a parent enables Websites:

- `/etc/chromium/policies/managed/90-omarchy-school-mode.json`
- `/etc/opt/chrome/policies/managed/90-omarchy-school-mode.json`
- `/etc/chromium/native-messaging-hosts/io.github.peterholko.school_mode.json`
- `/etc/opt/chrome/native-messaging-hosts/io.github.peterholko.school_mode.json`
- `/usr/bin/omarchy-kids-controls-school-websites`
- Private receipt and signing key: `/etc/omarchy-kids-controls/school-websites.json` and `school-websites-key.pem`
- Public signed package, update manifest and installation identity: `/var/lib/omarchy-kids-controls/school-websites/`

The daemon atomically replaces only the two owned policy files. Its systemd write allowance covers the managed policy directories so renames work; ownership checks reject symlinks and unrelated edits. Other policy files are read for collision detection but never written or deleted. The signing key is generated locally with OpenSSL, readable only by root, and retained across upgrades/removal to preserve the browser extension identity. The signed CRX3 package contains only the reviewed `service/browser-extension` sources. There are no remote scripts, package downloads or Web Store dependencies.

When needed, the service serves only `/update.xml` and `/school.crx` on `http://127.0.0.1:47651`. It does not bind to the LAN, provide configuration endpoints or expose arbitrary files. Chrome's updater authenticates the extension with its stable package signature. A port collision is a visible setup error; it is not ignored or replaced with another listener.

Native messaging uses bounded length-prefixed JSON over stdin/stdout. The unprivileged Python bridge connects only to `/run/omarchy-kids-controls/sock`, ignoring user environment overrides. Browser messages can request public rules or acknowledge their generation; they cannot relay parent commands, credentials, arbitrary socket paths or another user's identity. The daemon's existing socket peer authentication protects writes. Acknowledgements are bounded and informational; they never authorize a mode/configuration change.

## Troubleshooting and removal

After updating, run the repository's `setup --user CHILD_USERNAME --upgrade`. Enable Websites in the parent settings, save, and reopen Chrome/Chromium. The local companion is named **School Mode Websites**. `chrome://policy` shows this plugin's `URLBlocklist`, `ExtensionSettings` and extension-managed setting after refresh. `chrome://extensions` shows the installed companion. A policy update may take time on initial installation; the Websites tab remains waiting until a browser acknowledges it.

If a conflict is reported, inspect the named administrator policy file and decide which tool should manage website rules. Do not delete unrelated policies simply to bypass this check. Turning Websites off clears this plugin's policies without changing the other file. If the local installer cannot bind its loopback port, resolve the collision and restart `omarchy-kids-controls.service`.

Use `sudo omarchy-kids-controls remove school` before removing the shell plugin. This releases enrollments and removes only owned integration files after checking their ownership/content. Browser policy removal releases the companion. Parent settings, the local signing key, package and game history remain for a deliberate reinstall.

## Local checks

Python tests use temporary root/config/policy trees; OpenSSL verifies the generated CRX signature and an ephemeral loopback server verifies its fixed asset paths. Node tests cover domain boundaries, persistent browser rules, update ordering, existing-tab replacement and removal. The native Qt rendering check covers all three tabs, parent-password stdin, save/error feedback and larger text.

With Playwright and a local Chromium/Chrome for Testing binary already installed, the optional browser test uses a fresh temporary profile and local HTTP pages:

```bash
CHROMIUM_EXECUTABLE=/path/to/chromium node tests/browser-websites.cjs
```

Set `PLAYWRIGHT_MODULE` to an installed Playwright module path if it is not in the local Node resolution path, and optionally set `BROWSER_SCREENSHOT` to a PNG output path. This tests real request blocking, subdomains, already-open tabs and Free Time restoration. The native transport and managed-storage input are fixtures so no host browser policies or native messaging registrations are installed. The temporary browser and local HTTP server are closed afterward.

Linux policy loading, force-install from the signed package, systemd permissions and native-host registration still require a manual Omarchy laptop check: enable a test domain, reopen the browser, confirm browser receipt, enter Free Time and open the domain, switch to School Mode with its tab already open, and verify the notice replaces it. Return to Free Time and retry. Check reboot in School Mode and disabling the setting. No GitHub Actions, paid CI, ISO or VM testing is involved.

Primary references: [Chrome's Linux policy layout](https://www.chromium.org/administrators/linux-quick-start/), [URL pattern format](https://support.google.com/chrome/a/answer/9942583), [self-hosted Linux extensions](https://developer.chrome.com/docs/extensions/how-to/distribute/host-on-linux), [native messaging](https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging), and [Chromium's CRX3 creator](https://chromium.googlesource.com/chromium/src/+/main/components/crx_file/crx_creator.cc).
