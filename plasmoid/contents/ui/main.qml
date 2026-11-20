pragma ComponentBehavior: Bound

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
    property bool showDetails: false
    property bool detailsLoaded: false
    property bool hasUnlistedMutes: false
    property BackendRequest activeRequest: null
    property var queuedActions: []

    readonly property string backendPath: decodeURIComponent(Qt.resolvedUrl("../scripts/bridge.py").toString().replace(/^file:\/\//, ""))

    signal rowLayoutChanged

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
            muted: isMuted(app)
        };
    }

    function syncVisibleRows() {
        var wanted = [];
        var keep = Object.create(null);
        var layoutChanged = false;
        var resetPending = (activeRequest && !activeRequest.completed && activeRequest.edit.action === "reset")
                           || queuedActions.some(edit => edit.action === "reset");
        var anyMuted = hasUnlistedMutes && !resetPending;
        for (var n = 0; n < apps.length; ++n) {
            var row = normalizedRow(apps[n]);
            if (!row.label) {
                var task = taskForSource(row);
                row.label = task && task.appName ? task.appName : row.name;
            }
            wanted.push(row);
            keep[row.key] = true;
            anyMuted = anyMuted || row.muted;
        }
        wanted.sort(function(left, right) {
            if (left.microphone !== right.microphone) {
                return left.microphone ? -1 : 1;
            }
            var order = left.label.toLocaleLowerCase().localeCompare(right.label.toLocaleLowerCase());
            return order || (left.key < right.key ? -1 : left.key > right.key ? 1 : 0);
        });
        hasMutes = anyMuted;
        for (var j = visibleRows.count - 1; j >= 0; --j) {
            if (!keep[visibleRows.get(j).key]) {
                visibleRows.remove(j);
                layoutChanged = true;
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
            rowLayoutChanged();
        }
    }

    Plasmoid.icon: "org.cachy.steamaudiocontrol"
    toolTipMainText: ""
    toolTipSubText: ""
    hideOnWindowDeactivate: true
    Plasmoid.status: root.recordingActive ? PlasmaCore.Types.ActiveStatus : PlasmaCore.Types.PassiveStatus
    Plasmoid.hasConfigurationInterface: false

    Component.onCompleted: {
        Plasmoid.removeInternalAction("configure");
        request("status", "");
    }

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

    function isMuted(app) {
        var muted = Boolean(app.muted);
        var edits = activeRequest && !activeRequest.completed ? [activeRequest.edit].concat(queuedActions) : queuedActions;
        for (var edit of edits) {
            if (edit.action === "reset") {
                muted = false;
            } else if (edit.key === app.key) {
                muted = edit.muted;
            }
        }
        return muted;
    }

    function request(action, key) {
        if (action === "status") {
            if (!activeRequest) {
                startRequest({ action: "status" });
            }
            return;
        }
        if (action === "reset") {
            queuedActions = [{ action: "reset" }];
        } else {
            var app = apps.find(entry => entry.key === key);
            if (!app) {
                return;
            }
            var edit = { action: "set-muted", key: key, muted: !isMuted(app) };
            queuedActions = queuedActions.filter(entry => entry.key !== key).concat(edit);
        }
        runNextEdit();
        syncVisibleRows();
    }

    function runNextEdit() {
        if (!activeRequest && queuedActions.length) {
            var next = queuedActions[0];
            queuedActions = queuedActions.slice(1);
            startRequest(next);
        }
    }

    function startRequest(edit) {
        var key = edit.key ? hexEncode(edit.key) : "''";
        var routingOnly = edit.action === "status" && !showDetails;
        var command = "/usr/bin/timeout -k 2s 30s /usr/bin/python3 -B " + quote(backendPath)
                      + " " + edit.action + " " + key + " " + Plasmoid.id + " --widget";
        if (edit.action === "set-muted") {
            command += edit.muted ? " --muted" : " --unmuted";
        } else if (routingOnly) {
            command += " --routing-only";
        }
        activeRequest = backendRequest.createObject(root, { command: command, edit: edit, routingOnly: routingOnly });
        requestDeadline.restart();
        activeRequest.connectSource(command);
    }

    function finishRequest(job, data) {
        if (!job || job !== activeRequest || job.completed) {
            return;
        }
        requestDeadline.stop();
        job.completed = true;
        releaseDeadline.restart();
        job.disconnectSource(job.command);
        if (!data || data["exit code"] === 124 || data["exit code"] === 137) {
            errorMessage = i18n("The audio backend did not respond in time.");
        } else {
            try {
                var response = JSON.parse(data["stdout"]);
                if (data["exit code"] !== 0 || !response) {
                    throw new Error(data["stderr"] || data["exit code"]);
                }
                if (typeof response.active === "boolean") {
                    recordingActive = response.active;
                    microphoneActive = Boolean(response.microphoneActive);
                    if (Array.isArray(response.apps)) {
                        apps = response.apps;
                        detailsLoaded = true;
                        hasUnlistedMutes = Boolean(response.hasUnlistedMutes);
                        queuedActions = queuedActions.filter(edit => edit.action === "reset"
                            || apps.some(app => app.key === edit.key));
                    }
                } else if (!response.error) {
                    throw new Error(data["stdout"]);
                }
                errorMessage = response.error ? i18n("Audio backend: %1", response.error) : "";
            } catch (ex) {
                errorMessage = i18n("Invalid backend response: %1", String(data["stderr"] || ex).slice(0, 240));
            }
        }
        if (showDetails) {
            syncVisibleRows();
        }
    }

    function releaseRequest(job) {
        if (!job || job !== activeRequest) {
            return;
        }
        releaseDeadline.stop();
        var refreshDetails = job.routingOnly && showDetails;
        activeRequest = null;
        job.destroy();
        runNextEdit();
        if (refreshDetails) {
            request("status", "");
        }
    }

    component BackendRequest: Plasma5Support.DataSource {
        id: job
        required property string command
        required property var edit
        required property bool routingOnly
        property bool completed: false
        engine: "executable"
        onNewData: function(source, data) {
            if (source === job.command) {
                root.finishRequest(job, data);
            }
        }
        onSourceRemoved: function(source) {
            if (job.completed && source === job.command) {
                Qt.callLater(root.releaseRequest, job);
            }
        }
    }

    Component { id: backendRequest; BackendRequest {} }

    Timer {
        id: requestDeadline
        interval: 35000
        onTriggered: root.finishRequest(root.activeRequest, null)
    }

    Timer {
        id: releaseDeadline
        interval: 250
        onTriggered: root.releaseRequest(root.activeRequest)
    }

    Timer {
        interval: 1300
        repeat: true
        running: true
        onTriggered: root.request("status", "")
    }

    onShowDetailsChanged: {
        if (showDetails) {
            request("status", "");
        }
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

    component WindowTasks: Repeater {
        model: TaskManager.TasksModel {
            groupMode: TaskManager.TasksModel.GroupDisabled
            filterByScreen: false
            filterByVirtualDesktop: false
            filterByActivity: false
            filterHidden: false
            separateLaunchers: false
        }
        delegate: WindowTask {}
    }

    Loader {
        id: taskLookup
        active: root.showDetails
        sourceComponent: WindowTasks {}
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
        var tasks = taskLookup.item as WindowTasks;
        for (var i = 0; tasks && i < tasks.count; ++i) {
            var task = tasks.itemAt(i) as WindowTask;
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

        readonly property bool detailsVisible: visible && !!Window.window && Window.window.visible
        property int rowLayoutRevision: 0
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

        Binding {
            root.showDetails: panelContents.detailsVisible
        }

        Connections {
            target: root
            function onRowLayoutChanged() {
                sourcesView.forceLayout();
                panelContents.rowLayoutRevision++;
            }
        }

        ColumnLayout {
            anchors.fill: parent
            spacing: 0

            PlasmaComponents.ToolButton {
                Layout.alignment: Qt.AlignLeft
                Layout.margins: Kirigami.Units.smallSpacing
                Layout.leftMargin: Kirigami.Units.smallSpacing * 2
                text: i18n("Include all audio")
                enabled: root.hasMutes
                onClicked: root.request("reset", "")
            }

            Item {
                Layout.fillWidth: true
                Layout.fillHeight: true

                ListView {
                    id: sourcesView
                    anchors.fill: parent
                    clip: true
                    boundsBehavior: Flickable.StopAtBounds
                    model: panelContents.detailsVisible ? visibleRows : null
                    spacing: 0

                    HoverHandler { id: listPointer }

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
                        required property int index
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

                        Rectangle {
                            anchors.fill: parent
                            anchors.leftMargin: 2
                            anchors.rightMargin: 2
                            anchors.topMargin: 2
                            anchors.bottomMargin: 2
                            visible: panelContents.hoveredRowIndex === sourceRow.index
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
                                    sourceSize.width: Kirigami.Units.iconSizes.medium
                                    sourceSize.height: Kirigami.Units.iconSizes.medium
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
                                            if (sourceRow.capturing) {
                                                return root.errorMessage ? i18n("Mute selection saved") : i18n("Muted in Steam recording");
                                            }
                                            return i18n("Will be muted when Steam records this source");
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
                    visible: root.detailsLoaded && visibleRows.count === 0
                    color: Kirigami.Theme.disabledTextColor
                    text: i18n("No audio sources detected")
                }
            }

            PlasmaComponents.Label {
                Layout.fillWidth: true
                Layout.margins: Kirigami.Units.smallSpacing
                Layout.leftMargin: Kirigami.Units.smallSpacing * 2
                Layout.rightMargin: Kirigami.Units.smallSpacing * 2
                visible: root.errorMessage.length > 0
                text: root.errorMessage
                wrapMode: Text.WordWrap
                color: Kirigami.Theme.negativeTextColor
                font.pixelSize: Kirigami.Theme.smallFont.pixelSize
            }
        }
    }
}
