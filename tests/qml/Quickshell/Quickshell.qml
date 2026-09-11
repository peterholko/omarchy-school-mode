pragma Singleton
import QtQml

QtObject {
  property var detachedCommands: []
  function env(name) { return "/nonexistent-school-menu-test" }
  // Record the request without starting any process.
  function execDetached(command) { detachedCommands = detachedCommands.concat([command]) }
}
