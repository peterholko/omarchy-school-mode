import QtQuick
import qs.Ui

TextField {
  property bool checking: false
  password: true
  placeholderText: checking ? "Checking password…" : "Parent password"
  readOnly: checking
  cursorVisible: activeFocus && !checking
}
