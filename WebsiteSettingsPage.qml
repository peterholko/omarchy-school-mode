import QtQuick
import QtQuick.Controls as Controls
import qs.Ui
import qs.Commons

Column {
  id: root
  spacing: Style.space(14)
  property bool filteringEnabled: false
  property string domainText: ""
  property bool saving: false
  property var status: ({})
  signal saveRequested(var patch)

  function statusText() {
    if (status.error) {
      if (status.error === "managed_policy_missing") return "Reopen Chrome or Chromium to finish the website setup."
      if (status.error === "outdated_companion") return "Reopen Chrome or Chromium to update website protection."
      if (status.error === "apply_failed") return "The browser could not apply the rules. Reopen it and check again."
      return String(status.error)
    }
    if (!status.ready) return "Website setup is needed. Run the updated School Mode setup for this account."
    if (status.otherAccounts) return "Another account is in School Mode. Its website restrictions still apply on this laptop."
    if (!status.enabled) return "Website restrictions are off."
    if (!status.browserReceived) return "Waiting for a browser to receive the rules. Reopen Chrome or Chromium after the first setup."
    return status.activeDomains > 0 ? "Browser received the School Mode rules." : "Browser received the rules. No school websites are blocked right now."
  }

  PanelSectionHeader { text: "WEBSITES DURING SCHOOL"; foreground: Color.foreground }
  Toggle {
    objectName: "websiteFilteringToggle"
    width: parent.width
    label: "Block selected websites"
    description: "Only while School Mode is active."
    checked: root.filteringEnabled
    enabled: !root.saving
    onClicked: root.filteringEnabled = !root.filteringEnabled
  }
  Text {
    width: parent.width; wrapMode: Text.WordWrap; textFormat: Text.PlainText
    text: "Enter one domain per line, for example youtube.com. Its subdomains are included. Free Time allows these websites again."
    color: Color.foreground; font.family: Style.font.family; font.pixelSize: Style.font.body
  }
  Controls.ScrollView {
    width: parent.width; height: Style.space(155)
    clip: true
    Controls.ScrollBar.horizontal.policy: Controls.ScrollBar.AlwaysOff
    Controls.TextArea {
      id: domainsField
      objectName: "blockedDomainsField"
      text: root.domainText
      onTextChanged: root.domainText = text
      placeholderText: "youtube.com\nroblox.com"
      color: Color.foreground
      placeholderTextColor: Qt.alpha(Color.foreground, 0.45)
      selectionColor: Color.accent
      selectedTextColor: Color.background
      font.family: Style.font.family; font.pixelSize: Style.font.body
      wrapMode: TextEdit.WrapAnywhere
      padding: Style.space(10)
      selectByMouse: true
      activeFocusOnTab: true
      enabled: !root.saving
      background: Rectangle { color: Color.background; border.color: Qt.alpha(Color.foreground, 0.4); border.width: 1 }
    }
  }
  Button {
    objectName: "saveWebsitesButton"
    text: root.saving ? "Saving…" : "Save websites"
    enabled: !root.saving
    focusable: true
    onClicked: root.saveRequested({websites_enabled: root.filteringEnabled,
      school_blocked_domains: root.domainText.split(/\r?\n/).map(function(domain) { return domain.trim() }).filter(function(domain) { return domain !== "" })})
  }
  PanelSeparator { width: parent.width }
  Text {
    objectName: "websiteFilteringStatus"
    width: parent.width; wrapMode: Text.WordWrap; textFormat: Text.PlainText
    text: root.statusText()
    color: Color.foreground; font.family: Style.font.family; font.pixelSize: Style.font.body
  }
  Text {
    width: parent.width; wrapMode: Text.WordWrap; textFormat: Text.PlainText
    text: "Supports Chrome and Chromium. Blocked tabs in regular browser windows switch to a School Mode notice. Browser rules apply to every account on this laptop; other browsers and apps are outside this setting."
    color: Qt.alpha(Color.foreground, 0.65); font.family: Style.font.family; font.pixelSize: Style.font.caption
  }
}
