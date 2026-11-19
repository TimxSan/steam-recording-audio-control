# Steam Recording Audio Control

Native KDE Plasma 6 system tray widget to mute individual applications in Steam recordings.

## Install

```bash
git clone https://github.com/TimxSan/steam-recording-audio-control
./install.sh
```

## Uninstall

```bash
./uninstall.sh
```

Uninstallation restores Steam recording audio, then removes the widget, tray icon, saved preferences, session state, and any Steam-specific icon cache from older installations. If restoration fails, the script stops and keeps the recovery state. The legacy icon cache shared with Discord Stream Audio Control remains available to it.

## Icons

Audio sources, row controls, and the tray entry use icons bundled with the widget.
