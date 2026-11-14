var widgetName = "org.cachy.steamaudiocontrol";
for (var panel of panels()) {
    for (var widget of panel.widgets()) {
        if (widget.type !== "org.kde.plasma.systemtray") {
            continue;
        }
        var tray = widget;
        var containmentId = widget.readConfig("SystrayContainmentId");
        if (containmentId) {
            tray = desktopById(Number(containmentId)) || widget;
        }
        tray.currentConfigGroup = ["General"];
        var original = String(tray.readConfig("extraItems") || "").split(",").filter(function(item) {
            return item.length > 0;
        });
        var updated = original.filter(function(item) {
            return item !== widgetName;
        });
        if (original.length !== updated.length) {
            tray.writeConfig("extraItems", updated);
            tray.reloadConfig();
        }
    }
}
