// The mode comes from the screen-time daemon's status.json, the file the
// lock screen and Math time read too: school hours are school mode, and the
// daemon also holds the kid's own choice and the parent's override.
function parseStatus(rawText) {
  var fallback = { valid: false, blockedPeriods: [], enabled: false, mode: "free", reason: "", schoolApps: [], schoolUntil: "", schoolLabel: "" }
  var text = String(rawText || "").trim()
  if (!text) return fallback
  var parsed
  try {
    parsed = JSON.parse(text)
  } catch (error) {
    return fallback
  }
  if (!parsed || typeof parsed !== "object") return fallback
  if (typeof parsed.enabled !== "boolean" || (parsed.enabled && parsed.mode !== "school" && parsed.mode !== "free")) return fallback
  return {
    valid: true,
    blockedPeriods: Array.isArray(parsed.blockedPeriods) ? parsed.blockedPeriods : [],
    enabled: parsed.enabled === true,
    mode: parsed.mode === "school" ? "school" : "free",
    reason: String(parsed.modeReason || ""),
    schoolApps: Array.isArray(parsed.schoolApps) ? parsed.schoolApps.map(function(id) { return String(id) }) : [],
    schoolUntil: String(parsed.schoolUntil || ""),
    schoolLabel: String(parsed.schoolLabel || "")
  }
}

function schoolMode(status) {
  return !!status && status.enabled === true && status.mode === "school"
}

// What the pill's panel says about why.
function reasonLine(status) {
  if (!status || !status.enabled) return "School mode is off"
  if (status.mode === "school") {
    if (status.reason === "schedule") return (status.schoolLabel || "School") + (status.schoolUntil ? " until " + status.schoolUntil : "")
    if (status.reason === "parent") return "Set by a parent"
    if (status.reason === "chosen") return "Chosen for today"
    return "School mode"
  }
  if (status.reason === "parent") return "Free time, set by a parent" + (status.schoolUntil ? " until " + status.schoolUntil : "")
  return "Free time"
}

if (typeof module !== "undefined") {
  module.exports = { parseStatus: parseStatus, schoolMode: schoolMode, reasonLine: reasonLine }
}
