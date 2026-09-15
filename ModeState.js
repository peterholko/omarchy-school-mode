// Read-only status from the standalone School / Free Time service.
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
  if (!parsed || typeof parsed !== "object" || parsed.schemaVersion !== 1) return fallback
  if (typeof parsed.enabled !== "boolean" || (parsed.enabled && parsed.mode !== "school" && parsed.mode !== "free")) return fallback
  return {
    valid: true,
    blockedPeriods: Array.isArray(parsed.blockedPeriods) ? parsed.blockedPeriods : [],
    enabled: parsed.enabled === true,
    mode: parsed.mode === "school" ? "school" : "free",
    reason: String(parsed.modeReason || ""),
    schoolApps: Array.isArray(parsed.schoolApps) ? parsed.schoolApps.map(function(id) { return String(id) }) : [],
    schoolUntil: String(parsed.schoolUntil || ""),
    schoolLabel: String(parsed.schoolLabel || ""),
    timerVersion: parsed.freeTimeTimerVersion === 1 ? 1 : 0,
    timerReady: parsed.freeTimeReady === true,
    updatedAt: Number.isFinite(parsed.updatedAt) ? parsed.updatedAt : 0,
    freeTimeMinutes: Number.isInteger(parsed.freeTimeMinutes) ? parsed.freeTimeMinutes : 30,
    freeTimeRemainingSeconds: Number.isFinite(parsed.freeTimeRemainingSeconds) ? Math.max(0, parsed.freeTimeRemainingSeconds) : 0,
    freeTimeExpired: parsed.freeTimeExpired === true,
    websites: parsed.websites && typeof parsed.websites === "object" ? parsed.websites : ({})
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
    return "Ready for school. A parent can start Free Time."
  }
  if (status.reason === "expired") return "Time is up. The parent password returns you to School Mode."
  if (status.reason === "parent") return "Free Time, started by a parent"
  return "Free time"
}

if (typeof module !== "undefined") {
  module.exports = { parseStatus: parseStatus, schoolMode: schoolMode, reasonLine: reasonLine }
}
