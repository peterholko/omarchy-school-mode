# School website integration

The parent profile stores `websites_enabled` (default false) and `school_blocked_domains` (default empty). The existing authenticated `school config patch` route validates the complete patch before saving it. Old profiles acquire the disabled default. Domain lists accept DNS hostnames and an optional leading `*.`; matching always includes the host and its subdomains. Arbitrary browser URL patterns, paths, ports and IP addresses are rejected. At most 100 distinct domains may be configured across enrolled profiles.

## Enforcement and scope

The root service computes the union of enabled domain lists whose enrolled accounts are in School Mode. It publishes that list through Chrome/Chromium's managed `URLBlocklist` and through a locally installed Manifest V3 companion. The browser's policies are machine-wide, including adult accounts; they are not per-profile Linux policies. This is intended for a dedicated child laptop.

The companion applies dynamic request-blocking rules, including subdomains and embedded requests. On receipt of a new list it checks existing regular tabs and replaces matching top-level pages with its local notice, stopping those pages. It rechecks a tab immediately before navigation to avoid replacing a tab that has meanwhile moved to school work. The original URL stays in the local notice fragment for an explicit retry after Free Time. It is never sent to the native bridge or service. Already loaded content embedded in an unrelated page is not removed; future requests to the blocked host are denied. Existing Incognito/Guest content is outside this tab handling. The URL policy still restricts new navigations there.

The extension's native connection polls every two seconds. The service checks schedules on its normal tick, including reboot restoration and expiry-parent-unlock transitions. Browser receipt is informational: it confirms the latest generation was acknowledged by connected companion instances for the current account, not that every possible browser/profile is protected. The interface reports missing setup, pending browser startup, stale companion versions, policy conflicts and application errors instead of treating a saved list as proof of enforcement.

Transient service restarts retain the last browser request rules. Free Time clears only this extension's rules and removes this plugin's `URLBlocklist`. Disabling Websites or removing the School module removes its force-install/managed flag; the companion clears its persistent rules on managed-policy removal. Existing administrator policies and other extensions are never modified. Conflicts with `URLBlocklist`, `URLAllowlist`, `ExtensionSettings` or `ExtensionInstallForcelist` in other managed/recommended JSON files stop activation, since Chrome does not define precedence between files setting the same policy. Conflicts introduced afterward are reported; Free Time still removes our old School block list.

## Cloudflare Family DNS

The `family_dns_enabled` boolean is a laptop-wide setting in the root-owned School Mode configuration, defaulting to false. It is changed through the existing parent-authenticated `config.patch` endpoint and is shared across profiles. It is independent of `websites_enabled`, the domain list, the school schedule and the Free Time deadline. It remains active while any School Mode account is enrolled, in either mode; disabling the last enrollment or removing School Mode restores normal DNS. Re-enrollment retains the parent's preference.

Setup creates inert, owned configuration files and does not change DNS until a parent enables the toggle. The background worker applies:

- `/etc/NetworkManager/conf.d/99-omarchy-school-family-dns.conf`: the four Cloudflare malware/adult-filtering addresses as global DNS; direct DNS management for resolv.conf clients, with per-link updates to systemd-resolved disabled.
- `/etc/systemd/resolved.conf.d/99-omarchy-school-family-dns.conf`: the same four servers, an empty fallback list and the root routing domain for systemd-resolved clients. Server names also support an existing DNS-over-TLS configuration.
- `/etc/chromium/policies/managed/91-omarchy-school-family-dns.json` and `/etc/opt/chrome/policies/managed/91-omarchy-school-family-dns.json`: `DnsOverHttpsMode=off` so these browsers use the system resolver. Removal restores their previous Secure DNS preference. This works without the School Mode browser companion.

The NetworkManager and resolved paths are both needed: globally overriding NetworkManager's resolv.conf list alone does not replace the per-link DNS sent to systemd-resolved. Resolved also persists its D-Bus per-link settings across service restarts. After disabling NetworkManager's resolved updates and restarting resolved, the worker reads its server lists, checks each interface's `GENERAL.NM-MANAGED` flag and clears the DNS list only on NetworkManager-managed links with `resolvectl dns LINK ""`. This removes retained router/DHCP servers for both IPv4 and IPv6; it leaves each link's mDNS, LLMNR and routing settings alone. Global DNS and interfaces managed by other tools are not cleared and still cause verification to fail if they advertise unfiltered servers.

No connection profiles, routes, firewall rules or resolv.conf symlinks are edited by this plugin, and Wi-Fi is not disconnected. Disabling or rolling back removes this plugin's overrides and reloads NetworkManager's DNS configuration, letting it republish the current connection's servers. The worker does not restore a saved router address that could belong to a previous Wi-Fi network. Unfiltered fallback servers are not added while enabled.

The worker verifies NetworkManager's effective configuration, resolved's advertised DNS servers and resolv.conf before reporting active. This verifies resolver configuration, not Internet reachability or Cloudflare's categorization of every domain. DNS caches and existing browser connections may take time to expire; reopen the browser when testing a change. The operation runs outside the timer thread so unavailable network services do not delay a timer lock. Errors are published under `websites.familyDns` and retried after 30 seconds. The toggle reflects the parent's saved preference; the status below it reports whether that preference has been applied.

A private receipt at `/etc/omarchy-kids-controls/school-family-dns.json` records ownership and interrupted updates. Writes are atomic, serialized against removal, and rolled back on failure. Updates preserve enabled settings; an interrupted application is retried after service restart. Setup/removal reject unknown files, symlinked configuration paths and local edits. Existing NetworkManager global DNS or managed browser Secure DNS policies are reported as conflicts instead of being overwritten. Standard Omarchy NetworkManager/resolved setups are supported; other DNS managers require an administrator to restore a supported setup first.

Applications that supply their own resolver, proxies and VPNs are outside this resolver setting's enforcement. Cloudflare sees DNS lookups while enabled. Private network names and captive portals can require temporarily disabling it with parent approval. The setting neither changes Google account restrictions nor inspects browsing history. [Cloudflare resolver addresses](https://developers.cloudflare.com/1.1.1.1/ip-addresses/), [NetworkManager global DNS and resolver management](https://www.networkmanager.dev/docs/api/latest/NetworkManager.conf.html), and [DNS reload flags](https://networkmanager.pages.freedesktop.org/NetworkManager/NetworkManager/gdbus-org.freedesktop.NetworkManager.html) describe the underlying interfaces.

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

If version 2.3.1 reports an additional server such as your router's `192.168.1.1`, turn the toggle off and update both the plugin and service using the README commands. Version 2.3.2 (service 4.4.2) clears DNS retained on NetworkManager-managed links before verification. Then enable Family DNS again. The router remains the network gateway; no router settings need to change. If an additional server is still reported, `resolvectl dns` identifies whether it is global or belongs to an interface managed by another tool.

Version 2.3.0 could misread wrapped `resolvectl dns` output as a conflicting resolver, then fail restoration because it passed two separate reload flags to `nmcli`. Version 2.3.1 (service 4.4.1) fixes both. If that earlier attempt reported **DNS restoration also failed**, turn the Family DNS toggle off, then run these from the child's terminal to reload the restored network configuration:

```bash
sudo nmcli general reload conf &&
sudo nmcli general reload dns-full
```

Then update the plugin and run its `setup --user CHILD_USERNAME --upgrade --omarchy-path "$OMARCHY_PATH"` as described in the README before re-enabling the toggle. The fix keeps the existing configuration files and receipt, so an interrupted restoration can be resumed. Future command failures include the command and its error text; a real DNS mismatch lists the additional or missing resolver addresses. No administrator DNS files need to be deleted to fix the wrapped-output bug.

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

Linux policy loading, force-install from the signed package, systemd permissions and native-host registration still require a manual Omarchy laptop check: enable a test domain, reopen the browser, confirm browser receipt, enter Free Time and open the domain, switch to School Mode with its tab already open, and verify the notice replaces it. Return to Free Time and retry. Check reboot in School Mode and disabling the setting. For Family DNS, wait for the active status, check `resolvectl dns` for Cloudflare's addresses, switch modes, reconnect Wi-Fi and reboot, then turn the toggle off and confirm the previous network DNS returns. NetworkManager/resolved commands are mocked in local tests; actual Linux DNS configuration is not exercised on the development Mac. No GitHub Actions, paid CI, ISO or VM testing is involved.

Primary references: [Chrome's Linux policy layout](https://www.chromium.org/administrators/linux-quick-start/), [URL pattern format](https://support.google.com/chrome/a/answer/9942583), [self-hosted Linux extensions](https://developer.chrome.com/docs/extensions/how-to/distribute/host-on-linux), [native messaging](https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging), and [Chromium's CRX3 creator](https://chromium.googlesource.com/chromium/src/+/main/components/crx_file/crx_creator.cc).
