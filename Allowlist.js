// The school apps, by desktop id, as the daemon's profile lists them. The
// menu still resolves each through the installed DesktopEntries, so an absent
// app is never shown.
function normalizeDesktopId(value) {
  var id = String(value || "").trim()
  return id.slice(-8) === ".desktop" ? id.slice(0, -8) : id
}

function normalizeIds(values) {
  var source = Array.isArray(values) ? values : []
  var seen = ({})
  var result = []
  for (var i = 0; i < source.length; i++) {
    var id = normalizeDesktopId(source[i])
    if (!id || seen[id]) continue
    seen[id] = true
    result.push(id)
  }
  result.sort()
  return result
}

function idSet(values) {
  var ids = normalizeIds(values)
  var result = ({})
  for (var i = 0; i < ids.length; i++) result[ids[i]] = true
  return result
}

function contains(values, desktopId) {
  return idSet(values)[normalizeDesktopId(desktopId)] === true
}

function filterRows(rows, values) {
  var source = Array.isArray(rows) ? rows : []
  var allowed = idSet(values)
  var result = []
  for (var i = 0; i < source.length; i++) {
    var entry = source[i] && source[i].entry
    if (!entry) continue
    if (allowed[normalizeDesktopId(entry.id)] === true) result.push(source[i])
  }
  return result
}

if (typeof module !== "undefined") {
  module.exports = {
    normalizeDesktopId: normalizeDesktopId,
    normalizeIds: normalizeIds,
    contains: contains,
    filterRows: filterRows
  }
}
