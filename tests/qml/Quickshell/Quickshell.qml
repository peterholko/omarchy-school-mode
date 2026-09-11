pragma Singleton
import QtQml

QtObject {
  function env(name) { return "/nonexistent-school-menu-test" }
  function execDetached(command) { throw new Error("Desktop commands must not run in this test") }
}
