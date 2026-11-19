# Steam Recording Audio Control

Steam Recording Audio Control is a KDE Plasma 6 system tray widget that lets you mute individual apps in Steam Game Recording while keeping them audible during play. You can also mute Steam's microphone track while other apps continue to use the microphone.

## Requirements

- KDE Plasma 6 with `kpackagetool6`
- PipeWire with `pw-dump`, `pw-link`, and `pw-cli`
- Git and Python 3
- Steam with Game Recording enabled

## Install

```bash
git clone https://github.com/TimxSan/steam-recording-audio-control.git &&
cd steam-recording-audio-control &&
./install.sh
```

In **System Tray Settings → Entries**, enable **Steam Recording Audio Control** if needed and set its visibility to **Shown When Relevant**. While Steam is idle, open the tray's hidden items to find the widget.

## Update

Run this from your existing clone on the `main` branch.

```bash
git pull --ff-only origin main && ./install.sh
```

The installer upgrades the widget in place and keeps your saved mute selections. Both installation and updates can restart Plasma Shell to load the widget.

## Usage

Open the widget from the system tray and toggle the mute icon next to an app or the microphone. The list shows detected sources even while Steam is idle. App icons are used when available, with bundled category icons as a fallback.

- Enable **Save mutes** to choose sources before recording and apply the same selections automatically to future recordings.
- Leave **Save mutes** off to mute sources for the current recording only.
- Select **Include all audio** to clear all mute selections, including saved ones.

## Uninstall

Run this from the cloned repository.

```bash
./uninstall.sh
```

Uninstallation restores Steam recording audio and removes the widget, tray icon, saved preferences, session state, and any Steam-specific icon cache from older installations. If audio restoration fails, the script stops and keeps the recovery state. The legacy icon cache shared with Discord Stream Audio Control is preserved.

## License

[MIT](LICENSE)
