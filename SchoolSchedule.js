var DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

function clonePeriod(period) {
  period = period && typeof period === "object" ? period : ({})
  var days = Array.isArray(period.days) ? period.days : DAYS
  return {
    label: String(period.label || "School"),
    enabled: period.enabled === true,
    start: String(period.start || "08:30"),
    end: String(period.end || "15:00"),
    days: DAYS.filter(function(day) { return days.indexOf(day) >= 0 }),
    mode: period.mode === "free" ? "free" : "block"
  }
}

function schoolPeriods(periods) {
  var source = Array.isArray(periods) ? periods : []
  return source.filter(function(period) {
    return period && period.mode === "free"
  }).map(clonePeriod)
}

// blocked_periods is one shared daemon setting. The focused school editor
// replaces only its school-time entries and preserves bedtime, dinner, and
// every other locking period managed by Screen Time.
function merge(periods, schools) {
  var source = Array.isArray(periods) ? periods : []
  var replacements = Array.isArray(schools) ? schools : []
  var result = []
  var inserted = false

  function appendSchools() {
    for (var schoolIndex = 0; schoolIndex < replacements.length; schoolIndex++) {
      var school = clonePeriod(replacements[schoolIndex])
      school.mode = "free"
      if (!school.label.trim()) school.label = "School"
      result.push(school)
    }
    inserted = true
  }

  for (var i = 0; i < source.length; i++) {
    if (source[i] && source[i].mode === "free") {
      if (!inserted) appendSchools()
    } else {
      result.push(clonePeriod(source[i]))
    }
  }
  if (!inserted) appendSchools()
  return result
}

function clonePeriods(periods) {
  var source = Array.isArray(periods) ? periods : []
  return source.map(clonePeriod)
}

function toggleDay(periods, index, day) {
  var result = clonePeriods(periods)
  if (index < 0 || index >= result.length || DAYS.indexOf(day) < 0) return result
  var days = result[index].days.slice()
  var at = days.indexOf(day)
  if (at >= 0) {
    if (days.length <= 1) return result
    days.splice(at, 1)
  } else {
    days.push(day)
  }
  result[index].days = DAYS.filter(function(candidate) { return days.indexOf(candidate) >= 0 })
  return result
}

function validTime(text) {
  return /^([01]?\d|2[0-3]):[0-5]\d$/.test(String(text || ""))
}

if (typeof module !== "undefined") {
  module.exports = {
    DAYS: DAYS,
    clonePeriod: clonePeriod,
    schoolPeriods: schoolPeriods,
    merge: merge,
    clonePeriods: clonePeriods,
    toggleDay: toggleDay,
    validTime: validTime
  }
}
