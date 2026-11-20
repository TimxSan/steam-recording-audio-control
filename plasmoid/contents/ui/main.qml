import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.plasma.components as PlasmaComponents
import org.kde.kirigami as Kirigami
import org.kde.ksvg as KSvg
import org.kde.plasma.plasmoid
import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.plasma5support as Plasma5Support
import org.kde.taskmanager as TaskManager

PlasmoidItem {
    id: root

    property bool recordingActive: false
    property bool microphoneActive: false
    property bool hasMutes: false
    property var apps: []
    property string errorMessage: ""
    property int requestId: 0
    property string activeCommand: ""
    property var queuedActions: []

    ListModel { id: visibleRows }

    function normalizedRow(app) {
        var iconCategory = String(app.iconCategory || "");
        var name = String(app.name || "");
        var microphone = Boolean(app.microphone);
        return {
            key: String(app.key || ""),
            name: name,
            label: microphone ? (name ? i18n("Microphone (%1)", name) : i18n("Microphone"))
                              : String(app.applicationName || ""),
            icon: String(app.icon || ""),
            pid: Number(app.pid || 0),
            appId: String(app.appId || ""),
            binary: String(app.binary || ""),
            iconCategory: /^[a-z]+$/.test(iconCategory) ? iconCategory : "generic",
            microphone: microphone,
            sectionTitle: microphone ? i18n("Microphones") : i18n("Audio sources"),
            muted: Boolean(app.muted)
        };
    }

    function syncVisibleRows() {
        var wanted = [];
        var keep = Object.create(null);
        for (var n = 0; n < apps.length; ++n) {
            var row = normalizedRow(apps[n]);
            if (!row.label) {
                var task = taskForSource(row);
                row.label = task && task.appName ? task.appName : row.name;
            }
            wanted.push(row);
            keep[row.key] = true;
        }
        wanted.sort(function(left, right) {
            if (left.microphone !== right.microphone) {
                return left.microphone ? -1 : 1;
            }
            var order = left.label.toLocaleLowerCase().localeCompare(right.label.toLocaleLowerCase());
            return order || (left.key < right.key ? -1 : left.key > right.key ? 1 : 0);
        });
        for (var j = visibleRows.count - 1; j >= 0; --j) {
            if (!keep[visibleRows.get(j).key]) {
                visibleRows.remove(j);
            }
        }
        var fields = ["name", "label", "icon", "pid", "appId", "binary", "iconCategory", "microphone", "sectionTitle", "muted"];
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
                continue;
            }
            if (current !== i) {
                visibleRows.move(current, i, 1);
            }
            var existing = visibleRows.get(i);
            for (var f = 0; f < fields.length; ++f) {
                var field = fields[f];
                if (existing[field] !== next[field]) {
                    visibleRows.setProperty(i, field, next[field]);
                }
            }
        }
    }
    readonly property string backendPath: decodeURIComponent(Qt.resolvedUrl("../scripts/bridge.py").toString().replace(/^file:\/\//, ""))

    Plasmoid.icon: "org.cachy.steamaudiocontrol"
    Plasmoid.title: "Steam Recording Audio Control"
    toolTipMainText: ""
    toolTipSubText: ""
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

    function optimisticUpdate(action, key) {
        if (action === "reset") {
            hasMutes = false;
        }
        var updated = [];
        for (var i = 0; i < apps.length; ++i) {
            var next = Object.assign({}, apps[i]);
            if (action === "mute" && next.key === key) {
                next.muted = !Boolean(next.muted);
                hasMutes = hasMutes || next.muted;
            } else if (action === "reset") {
                next.muted = false;
            }
            updated.push(next);
        }
        apps = updated;
        syncVisibleRows();
    }

    function request(action, key) {
        if (action !== "status") {
            optimisticUpdate(action, key);
        }
        if (activeCommand) {
            if (action !== "status") {
                queuedActions.push({ action: action, key: key });
            }
            return;
        }
        startRequest(action, key);
    }

    function startRequest(action, key) {
        var argument = key ? hexEncode(key) : "''";
        activeCommand = "/usr/bin/python -B " + quote(backendPath) + " " + action + " " + argument + " " + (++requestId);
        commandEngine.connectSource(activeCommand);
    }

    function updateState(source, data) {
        if (source !== activeCommand) {
            return;
        }
        if (queuedActions.length > 0) {
            var next = queuedActions.shift();
            startRequest(next.action, next.key);
            return;
        }
        activeCommand = "";
        var response;
        try {
            response = JSON.parse(data["stdout"] || "{}");
        } catch (ex) {
            errorMessage = i18n("Invalid backend response: %1", ex);
            return;
        }
        recordingActive = Boolean(response.active);
        microphoneActive = Boolean(response.microphoneActive);
        hasMutes = Boolean(response.hasMutes);
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

    TaskManager.TasksModel {
        id: plasmaTasks
        groupMode: TaskManager.TasksModel.GroupDisabled
        filterByScreen: false
        filterByVirtualDesktop: false
        filterByActivity: false
        filterHidden: false
        separateLaunchers: false
    }

    component WindowTask: Item {
        required property var model
        readonly property string appId: String(model.AppId || "")
        readonly property string appName: String(model.AppName || "")
        readonly property int pid: Number(model.AppPid || 0)
        readonly property bool isWindow: Boolean(model.IsWindow)
        readonly property var icon: model.decoration
        visible: false
    }

    Repeater {
        id: taskRepeater
        model: plasmaTasks
        delegate: WindowTask {}
    }

    function normalizeTaskIdentity(value) {
        return String(value || "").toLowerCase().replace(/\.desktop$/, "")
            .replace(/\.exe$/, "").replace(/[^a-z0-9]+/g, "");
    }

    function taskForSource(app) {
        var pid = Number(app.pid || 0);
        var appId = normalizeTaskIdentity(app.appId);
        var name = normalizeTaskIdentity(app.name);
        var key = normalizeTaskIdentity(app.key);
        var binary = normalizeTaskIdentity(app.binary);
        var best = null;
        var bestScore = 0;
        for (var i = 0; i < taskRepeater.count; ++i) {
            var task = taskRepeater.itemAt(i) as WindowTask;
            if (!task || !task.isWindow) {
                continue;
            }
            var taskId = normalizeTaskIdentity(task.appId);
            var taskName = normalizeTaskIdentity(task.appName);
            var score = 0;
            if (pid > 0 && pid === task.pid) {
                score = 100;
            } else if (appId && appId === taskId) {
                score = 90;
            } else if (binary && taskId && binary === taskId) {
                score = 80;
            } else if (name && name.length >= 4 && (name === taskName || name === taskId)) {
                score = 70;
            } else if (key && key.length >= 4 && (key === taskName || key === taskId)) {
                score = 60;
            }
            if (score > bestScore) {
                bestScore = score;
                best = task;
            }
        }
        return best;
    }

    component SourceActionButton: PlasmaComponents.ToolButton {
        id: actionButton
        required property url iconFile
        display: QQC2.AbstractButton.IconOnly
        QQC2.ToolTip.text: actionButton.text
        QQC2.ToolTip.visible: actionButton.hovered

        contentItem: KSvg.SvgItem {
            implicitWidth: Kirigami.Units.iconSizes.smallMedium
            implicitHeight: Kirigami.Units.iconSizes.smallMedium
            imagePath: decodeURIComponent(actionButton.iconFile.toString().replace(/^file:\/\//, ""))
            opacity: actionButton.enabled ? 1 : 0.5
        }
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

            PlasmaComponents.ToolButton {
                Layout.alignment: Qt.AlignRight
                Layout.margins: Kirigami.Units.smallSpacing
                text: i18n("Include all audio")
                enabled: root.hasMutes
                onClicked: root.request("reset", "")
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
                    section.property: "sectionTitle"
                    section.delegate: Item {
                        id: sectionHeader
                        required property string section
                        width: sourcesView.width
                        height: titleRow.implicitHeight + Kirigami.Units.smallSpacing * 2

                        RowLayout {
                            id: titleRow
                            anchors.fill: parent
                            anchors.leftMargin: Kirigami.Units.smallSpacing * 2
                            anchors.rightMargin: Kirigami.Units.smallSpacing * 2
                            spacing: Kirigami.Units.smallSpacing

                            PlasmaComponents.Label {
                                text: sectionHeader.section
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
                    }

                    delegate: Item {
                        id: sourceRow
                        required property string key
                        required property string name
                        required property string label
                        required property string icon
                        required property int pid
                        required property string appId
                        required property string binary
                        required property string iconCategory
                        required property bool microphone
                        required property bool muted
                        readonly property bool capturing: microphone ? root.microphoneActive : root.recordingActive
                        width: ListView.view.width
                        height: Kirigami.Units.gridUnit * 2.75

                        HoverHandler { id: rowPointer }

                        Rectangle {
                            anchors.fill: parent
                            anchors.leftMargin: 2
                            anchors.rightMargin: 2
                            anchors.topMargin: 2
                            anchors.bottomMargin: 2
                            visible: rowPointer.hovered
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

                            Item {
                                id: sourceIcon
                                readonly property bool hasApplicationIcon: !!applicationIcon.source
                                                                         && applicationIcon.status === Kirigami.Icon.Ready
                                readonly property bool hasWindowIcon: !!windowIcon.source
                                                                     && windowIcon.status === Kirigami.Icon.Ready
                                Layout.preferredWidth: Kirigami.Units.iconSizes.medium
                                Layout.preferredHeight: Kirigami.Units.iconSizes.medium

                                Kirigami.Icon {
                                    id: applicationIcon
                                    anchors.fill: parent
                                    source: sourceRow.icon
                                    fallback: ""
                                    placeholder: ""
                                    visible: sourceIcon.hasApplicationIcon
                                }

                                Kirigami.Icon {
                                    id: windowIcon
                                    anchors.fill: parent
                                    source: {
                                        if (sourceIcon.hasApplicationIcon || sourceRow.microphone) {
                                            return null;
                                        }
                                        var task = root.taskForSource(sourceRow);
                                        return task ? task.icon : null;
                                    }
                                    fallback: ""
                                    placeholder: ""
                                    visible: sourceIcon.hasWindowIcon
                                }

                                Image {
                                    readonly property bool needed: !sourceIcon.hasApplicationIcon && !sourceIcon.hasWindowIcon
                                    anchors.fill: parent
                                    visible: needed
                                    source: needed ? "../icons/fallback/" + sourceRow.iconCategory + ".png" : ""
                                    fillMode: Image.PreserveAspectFit
                                }
                            }

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 0
                                PlasmaComponents.Label {
                                    Layout.fillWidth: true
                                    text: sourceRow.label
                                    elide: Text.ElideRight
                                    color: Kirigami.Theme.textColor
                                }
                                PlasmaComponents.Label {
                                    Layout.fillWidth: true
                                    text: {
                                        if (sourceRow.muted) {
                                            return sourceRow.capturing ? i18n("Muted in Steam recording")
                                                                       : i18n("Will be muted when Steam records this source");
                                        }
                                        if (sourceRow.capturing) {
                                            return i18n("Being recorded");
                                        }
                                        return root.recordingActive ? i18n("Steam is not recording the microphone")
                                                                    : i18n("No Steam recording active");
                                    }
                                    elide: Text.ElideRight
                                    color: Kirigami.Theme.disabledTextColor
                                    font.pixelSize: Kirigami.Theme.smallFont.pixelSize
                                }
                            }

                            SourceActionButton {
                                text: sourceRow.muted ? i18n("Unmute") : i18n("Mute")
                                iconFile: Qt.resolvedUrl(sourceRow.muted ? "../icons/muted.svg" : "../icons/audible.svg")
                                onClicked: root.request("mute", sourceRow.key)
                            }
                        }
                    }
                }

                PlasmaComponents.Label {
                    anchors.horizontalCenter: parent.horizontalCenter
                    anchors.verticalCenter: parent.verticalCenter
                    visible: visibleRows.count === 0
                    color: Kirigami.Theme.disabledTextColor
                    text: i18n("No audio sources detected")
                }
            }
        }
    }
}
