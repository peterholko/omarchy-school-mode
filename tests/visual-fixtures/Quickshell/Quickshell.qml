pragma Singleton
import QtQuick
QtObject {
  property var detachedCommands: []
  property var writes: []
  function env(name) { return "/nonexistent-school-ui-qa" }
  function execDetached(command) { detachedCommands = detachedCommands.concat([command]) }
}
