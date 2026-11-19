import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.plasma.components as PlasmaComponents
import org.kde.kirigami as Kirigami
import org.kde.plasma.plasmoid
import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.plasma5support as Plasma5Support

PlasmoidItem {
    id: root

    property bool recordingActive: false
    property bool showHidden: false
    property var apps: []
    property string errorMessage: ""
    property int requestId: 0
    property int latestApplied: 0
    property var requests: ({})
    property int rowLayoutRevision: 0
    onShowHiddenChanged: syncVisibleRows()
    readonly property int hoveredRowIndex: {
        var revision = rowLayoutRevision;
        if (!listPointer.hovered) {
            return -1;
        }
        return sourcesView.indexAt(
            listPointer.point.position.x + sourcesView.contentX,
            listPointer.point.position.y + sourcesView.contentY
        );
    }

    ListModel { id: visibleRows }

    function normalizedRow(app) {
        var iconCategory = String(app.iconCategory || "");
        return {
            key: String(app.key || ""),
            name: String(app.name || ""),
            iconCategory: /^[a-z]+$/.test(iconCategory) ? iconCategory : "generic",
            muted: Boolean(app.muted),
            hidden: Boolean(app.hidden)
        };
    }

    function syncVisibleRows() {
        var wanted = [];
        var keep = {};
        for (var n = 0; n < apps.length; ++n) {
            var row = normalizedRow(apps[n]);
            if (row.hidden !== showHidden) {
                continue;
            }
            wanted.push(row);
            keep[row.key] = true;
        }
        var layoutChanged = false;
        for (var j = visibleRows.count - 1; j >= 0; --j) {
            if (!keep[visibleRows.get(j).key]) {
                visibleRows.remove(j);
                layoutChanged = true;
            }
        }
        var fields = ["name", "iconCategory", "muted", "hidden"];
        for (var i = 0; i < wanted.length; ++i) {
            var next = wanted[i];
            var current = -1;
            for (var k = i; k < visibleRows.count; ++k) {
                if (visibleRows.get(k).key === next.key) {
                    current = k;
                    break;
                }
            }
            if (current === -1) {
                visibleRows.insert(i, next);
                layoutChanged = true;
                continue;
            }
            if (current !== i) {
                visibleRows.move(current, i, 1);
                layoutChanged = true;
            }
            var existing = visibleRows.get(i);
            for (var f = 0; f < fields.length; ++f) {
                var field = fields[f];
                if (existing[field] !== next[field]) {
                    visibleRows.setProperty(i, field, next[field]);
                }
            }
        }
        if (layoutChanged) {
            sourcesView.forceLayout();
            rowLayoutRevision++;
        }
    }
    readonly property string backendPath: decodeURIComponent(Qt.resolvedUrl("../scripts/bridge.py").toString().replace(/^file:\/\//, ""))

    Plasmoid.icon: "org.cachy.steamaudiocontrol"
    Plasmoid.title: "Steam Recording Audio Control"
    toolTipMainText: "Steam Recording Audio Control"
    toolTipSubText: i18n("Select audio sources for Steam recordings")
    hideOnWindowDeactivate: true
    Plasmoid.status: root.recordingActive ? PlasmaCore.Types.ActiveStatus : PlasmaCore.Types.PassiveStatus
    Plasmoid.hasConfigurationInterface: false

    Component.onCompleted: Plasmoid.removeInternalAction("configure")

    function hexEncode(value) {
        var text = String(value || "");
        var result = "";
        for (var i = 0; i < text.length; ++i) {
            var chars = text.charCodeAt(i).toString(16);
            result += ("0000" + chars).slice(-4);
        }
        return result;
    }

    function quote(value) {
        return "'" + value.replace(/'/g, "'\\''") + "'";
    }

    property int pendingActions: 0
    property int pendingStatusRequests: 0

    function optimisticUpdate(action, key) {
        if (action === "status") {
            return;
        }
        var updated = [];
        for (var i = 0; i < apps.length; ++i) {
            var next = Object.assign({}, apps[i]);
            if (action === "mute" && next.key === key) {
                next.muted = !Boolean(next.muted);
            } else if (action === "hide" && next.key === key) {
                next.hidden = !Boolean(next.hidden);
            } else if (action === "reset") {
                next.muted = false;
            }
            updated.push(next);
        }
        apps = updated;
        syncVisibleRows();
    }

    function request(action, key) {
        if (action === "status" && (pendingActions > 0 || pendingStatusRequests > 0)) {
            return;
        }
        var id = ++requestId;
        var command = "/usr/bin/python " + quote(backendPath) + " " + action + " " + hexEncode(key || "") + " " + id;
        if (!key) {
            command = "/usr/bin/python " + quote(backendPath) + " " + action + " '' " + id;
        }
        requests[command] = { id: id, action: action };
        if (action !== "status") {
            pendingActions++;
            latestApplied = id;
            optimisticUpdate(action, key);
        } else {
            pendingStatusRequests++;
        }
        commandEngine.connectSource(command);
    }

    function updateState(source, data) {
        var context = requests[source];
        delete requests[source];
        if (!context) {
            return;
        }
        if (context.action === "status") {
            pendingStatusRequests = Math.max(0, pendingStatusRequests - 1);
        }
        if (context.action !== "status") {
            pendingActions = Math.max(0, pendingActions - 1);
            if (pendingActions > 0) {
                return;
            }
            request("status", "");
        } else if (pendingActions > 0) {
            return;
        }
        if (context.id < latestApplied) {
            return;
        }
        var response;
        try {
            response = JSON.parse(data["stdout"] || "{}");
        } catch (ex) {
            errorMessage = i18n("Invalid backend response: %1", ex);
            return;
        }
        latestApplied = context.id;
        recordingActive = Boolean(response.active);
        apps = response.apps || [];
        syncVisibleRows();
        errorMessage = response.error || "";
    }

    Plasma5Support.DataSource {
        id: commandEngine
        engine: "executable"
        connectedSources: []
        onNewData: function(source, data) {
            disconnectSource(source);
            root.updateState(source, data);
        }
    }

    Timer {
        interval: 1300
        repeat: true
        running: true
        triggeredOnStart: true
        onTriggered: root.request("status", "")
    }

    fullRepresentation: Item {
        id: panelContents
        Layout.minimumWidth: 370
        Layout.minimumHeight: 360
        Layout.preferredWidth: 440
        Layout.preferredHeight: 440
        Layout.maximumWidth: 440
        Layout.maximumHeight: 550

        ColumnLayout {
            anchors.fill: parent
            spacing: 0

            RowLayout {
                Layout.fillWidth: true
                Layout.leftMargin: Kirigami.Units.smallSpacing
                Layout.rightMargin: Kirigami.Units.smallSpacing
                Layout.preferredHeight: Kirigami.Units.gridUnit * 2.6
                spacing: Kirigami.Units.smallSpacing

                PlasmaComponents.Switch {
                    id: hiddenSwitch
                    Layout.fillWidth: true
                    text: i18n("Show hidden")
                    checked: root.showHidden
                    onToggled: root.showHidden = checked
                    QQC2.ToolTip.text: i18n("Show hidden audio sources")
                    QQC2.ToolTip.visible: hovered
                }

                PlasmaComponents.ToolButton {
                    id: resetButton
                    text: i18n("Include all audio")
                    enabled: root.recordingActive && root.apps.some(function(a) { return Boolean(a.muted); })
                    onClicked: root.request("reset", "")
                    QQC2.ToolTip.text: i18n("Include all audio in the recording")
                    QQC2.ToolTip.visible: hovered
                }
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.leftMargin: Kirigami.Units.smallSpacing * 2
                Layout.rightMargin: Kirigami.Units.smallSpacing * 2
                Layout.topMargin: Kirigami.Units.smallSpacing
                Layout.bottomMargin: Kirigami.Units.smallSpacing
                spacing: Kirigami.Units.smallSpacing

                PlasmaComponents.Label {
                    text: root.showHidden ? i18n("Hidden audio sources") : i18n("Audio sources")
                    color: Kirigami.Theme.disabledTextColor
                    font.bold: true
                    font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                }
                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 1
                    color: Kirigami.Theme.textColor
                    opacity: 0.16
                }
            }

            PlasmaComponents.Label {
                Layout.fillWidth: true
                Layout.leftMargin: Kirigami.Units.smallSpacing * 2
                Layout.rightMargin: Kirigami.Units.smallSpacing * 2
                Layout.bottomMargin: Kirigami.Units.smallSpacing
                visible: root.errorMessage.length > 0
                text: root.errorMessage
                wrapMode: Text.WordWrap
                color: Kirigami.Theme.negativeTextColor
                font.pixelSize: Kirigami.Theme.smallFont.pixelSize
            }

            Item {
                Layout.fillWidth: true
                Layout.fillHeight: true

                ListView {
                    id: sourcesView
                    anchors.fill: parent
                    clip: true
                    boundsBehavior: Flickable.StopAtBounds
                    model: visibleRows
                    spacing: 0

                    HoverHandler {
                        id: listPointer
                    }

                    delegate: Item {
                        id: sourceRow
                        required property int index
                        required property string key
                        required property string name
                        required property string iconCategory
                        required property bool muted
                        required property bool hidden
                        width: ListView.view.width
                        height: Kirigami.Units.gridUnit * 2.75

                        Rectangle {
                            anchors.fill: parent
                            anchors.leftMargin: 2
                            anchors.rightMargin: 2
                            anchors.topMargin: 2
                            anchors.bottomMargin: 2
                            visible: root.hoveredRowIndex === sourceRow.index
                            color: "#264A5C"
                            border.color: "#3DAEE9"
                            border.width: 1
                            radius: 5
                        }

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: Kirigami.Units.smallSpacing * 2
                            anchors.rightMargin: Kirigami.Units.smallSpacing * 2
                            spacing: Kirigami.Units.smallSpacing * 2

                            Image {
                                source: "../icons/fallback/" + sourceRow.iconCategory + ".png"
                                fillMode: Image.PreserveAspectFit
                                Layout.preferredWidth: Kirigami.Units.iconSizes.medium
                                Layout.preferredHeight: Kirigami.Units.iconSizes.medium
                            }

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 0
                                PlasmaComponents.Label {
                                    Layout.fillWidth: true
                                    text: sourceRow.name
                                    elide: Text.ElideRight
                                    color: Kirigami.Theme.textColor
                                }
                                PlasmaComponents.Label {
                                    Layout.fillWidth: true
                                    text: sourceRow.muted ? i18n("Muted in Steam recording") :
                                          sourceRow.hidden ? i18n("Hidden from list") : i18n("Being recorded")
                                    elide: Text.ElideRight
                                    color: Kirigami.Theme.disabledTextColor
                                    font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                                }
                            }

                            PlasmaComponents.ToolButton {
                                text: sourceRow.hidden ? i18n("Show again") : i18n("Hide")
                                display: QQC2.AbstractButton.IconOnly
                                icon.source: sourceRow.hidden ? "../icons/show.svg" : "../icons/hide.svg"
                                visible: root.hoveredRowIndex === sourceRow.index || Boolean(sourceRow.hidden)
                                onClicked: root.request("hide", sourceRow.key)
                                QQC2.ToolTip.visible: false
                            }

                            PlasmaComponents.ToolButton {
                                text: sourceRow.muted ? i18n("Include in Steam recording") : i18n("Mute in Steam recording")
                                display: QQC2.AbstractButton.IconOnly
                                icon.source: sourceRow.muted ? "../icons/muted.svg" : "../icons/audible.svg"
                                onClicked: root.request("mute", sourceRow.key)
                                QQC2.ToolTip.visible: false
                            }
                        }
                    }
                }

                PlasmaComponents.Label {
                    anchors.horizontalCenter: parent.horizontalCenter
                    anchors.verticalCenter: parent.verticalCenter
                    visible: visibleRows.count === 0
                    color: Kirigami.Theme.disabledTextColor
                    text: root.showHidden ? i18n("No hidden applications") : i18n("No audio sources detected")
                }
            }
        }
    }
}
