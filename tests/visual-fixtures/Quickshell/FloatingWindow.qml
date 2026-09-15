import QtQuick
import QtQuick.Window
Window {
  id: root
  objectName: "settingsWindow"
  default property alias windowData: content.data
  property Item surface: Item { id: content; parent: root.contentItem; anchors.fill: parent }
  property int implicitWidth: 520
  property int implicitHeight: 660
  property size minimumSize: Qt.size(1, 1)
  property size maximumSize: Qt.size(2000, 2000)
  width: implicitWidth; height: implicitHeight
  onWidthChanged: contentItem.width = width
  onHeightChanged: contentItem.height = height
  Component.onCompleted: { contentItem.width = width; contentItem.height = height }
}
