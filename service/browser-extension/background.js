"use strict";

// No browsing URL leaves this extension. The native connection receives only
// fixed polls and acknowledgements of the public policy generation.
function blocked(url, domains) {
  try {
    const parsed = new URL(url);
    if (!["http:", "https:"].includes(parsed.protocol)) return false;
    const host = parsed.hostname.toLowerCase().replace(/\.$/, "");
    return domains.some(domain => host === domain || host.endsWith("." + domain));
  } catch (_) { return false; }
}

function rules(domains) {
  if (!domains.length) return [];
  return [{id: 1, priority: 1, action: {type: "block"}, condition: {
    requestDomains: domains,
    resourceTypes: ["main_frame", "sub_frame", "stylesheet", "script", "image", "font", "object", "xmlhttprequest", "ping", "csp_report", "media", "websocket", "other"]
  }}];
}

function controller(api) {
  let domains = [];
  let generation = null;
  let queue = Promise.resolve();
  const notice = api.runtime.getURL("blocked.html");

  async function redirect(tab) {
    const url = tab.pendingUrl || tab.url || "";
    if (blocked(url, domains)) {
      // Re-read before navigating: a user may have changed tabs while the
      // policy arrived. Never replace a newly opened, unrelated school page.
      try {
        const latest = await api.tabs.get(tab.id);
        const target = latest.pendingUrl || latest.url || "";
        if (blocked(target, domains)) await api.tabs.update(tab.id, {url: notice + "#" + encodeURIComponent(target)});
      } catch (_) { /* A tab closing during the update is harmless. */ }
    }
  }

  function apply(state) {
    const work = async () => {
      if (!state || state.ok !== true || !Array.isArray(state.domains) || typeof state.generation !== "string") return null;
      if (state.domains.length > 100 || state.domains.some(d => typeof d !== "string" || !/^[a-z0-9.-]+$/.test(d))) throw new Error("invalid domains");
      const outdated = state.enabled && state.version !== api.runtime.getManifest().version;
      const managed = await api.storage.managed.get("SchoolModeInstalled");
      if (state.enabled && managed.SchoolModeInstalled !== true) return "managed_policy_missing";
      if (generation !== state.generation) {
        const current = await api.declarativeNetRequest.getDynamicRules();
        await api.declarativeNetRequest.updateDynamicRules({removeRuleIds: current.map(r => r.id), addRules: rules(state.domains)});
        domains = state.domains.slice();
        await api.storage.local.set({domains, generation: state.generation});
        generation = state.generation;
      }
      await Promise.all((await api.tabs.query({})).map(redirect));
      return outdated ? "outdated_companion" : "";
    };
    const result = queue.then(work);
    queue = result.catch(() => {});
    return result;
  }

  async function restore() {
    const saved = await api.storage.local.get(["domains", "generation"]);
    domains = Array.isArray(saved.domains) ? saved.domains : [];
    // Reapply on the first status even after a worker restart; its JS state
    // must never be mistaken for confirmation of the actual DNR rules.
    const managed = await api.storage.managed.get("SchoolModeInstalled");
    if (managed.SchoolModeInstalled !== true) await clear();
    else await Promise.all((await api.tabs.query({})).map(redirect));
  }

  function clear() {
    const work = async () => {
      const current = await api.declarativeNetRequest.getDynamicRules();
      await api.declarativeNetRequest.updateDynamicRules({removeRuleIds: current.map(r => r.id), addRules: []});
      domains = []; generation = null;
      await api.storage.local.remove(["domains", "generation"]);
    };
    const result = queue.then(work);
    queue = result.catch(() => {});
    return result;
  }

  return {apply, restore, clear, redirect};
}

let startup = Promise.resolve();
if (typeof chrome !== "undefined") {
  const control = controller(chrome);
  const instance = crypto.randomUUID();
  let port = null;
  let interval = null;
  startup = control.restore().catch(() => {});

  function connect() {
    if (port) return;
    port = chrome.runtime.connectNative("io.github.peterholko.school_mode");
    const connection = port;
    connection.onMessage.addListener(state => {
      if (!state.domains) return;
      startup.then(() => control.apply(state)).then(error => {
        if (error !== null && port === connection) connection.postMessage({type: "ack", generation: state.generation, instance, error});
      }).catch(() => {
        if (port === connection) connection.postMessage({type: "ack", generation: state.generation, instance, error: "apply_failed"});
      });
    });
    connection.onDisconnect.addListener(() => {
      void chrome.runtime.lastError;
      clearInterval(interval); port = null;
      // Last installed DNR rules remain during a service restart. The managed
      // policy removal event below is the explicit uninstall/disable signal.
      setTimeout(connect, 2000);
    });
    connection.postMessage({type: "poll"});
    interval = setInterval(() => connection.postMessage({type: "poll"}), 2000);
  }

  chrome.tabs.onUpdated.addListener((_id, _change, tab) => { startup.then(() => control.redirect(tab)); });
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area === "managed" && changes.SchoolModeInstalled && changes.SchoolModeInstalled.newValue !== true) control.clear().catch(() => {});
  });
  // Alarms wake a worker if a missing native host let Chrome suspend it.
  chrome.alarms.create("reconnect", {periodInMinutes: 0.5});
  chrome.alarms.onAlarm.addListener(connect);
  startup.then(connect);
}

if (typeof module !== "undefined") module.exports = {blocked, rules, controller};
