# Steam Recording Audio Control

Native KDE Plasma 6 system tray widget to mute individual audio sources in Steam recordings.

The widget lists available audio streams and the microphone even when Steam is idle. Enable **Save mutes** to save mute selections and change them before recording starts. The widget applies them when it detects a Steam recording. With the switch off, mutes apply to the current recording only. The microphone control affects Steam's recording input while leaving other applications' microphone access intact.

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

Audio sources show their application icons when available, with bundled category icons as a fallback. The row controls and tray entry use bundled icons.
