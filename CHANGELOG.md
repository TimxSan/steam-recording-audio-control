# Changelog

## Unreleased

- Added this changelog and documented how to keep it up to date.
- Restored the hide, show, and mute button icons and use bundled category icons only when the application icon cannot be displayed.
- Show all audio sources by default and preserve manually hidden sources across restarts.
- Sort both source lists by the displayed application name and use PipeWire, desktop entries, Steam, and Plasma window metadata to identify applications and their icons.
- Require a widget version bump for every repository change.
- List audio sources while Steam is idle, allow advance mute selections, and mute Steam's microphone track independently of other applications.
- Remove widget tooltips and replace the reset button with a switch that saves mute selections and applies them automatically when Steam starts recording.
- Restore the Include All Audio button and place the mute-saving switch above Show Hidden.
- Add tooltips to the hide and mute controls and rename the switch to Save mutes.
- Remove source hiding and show all detected audio sources in one list.
- Show microphones in a separate section above the other audio sources.
- Keep mute icons at full opacity while Save mutes is being updated if muting is available.
- Queue widget actions in order and keep mute controls responsive while saving preferences.
- Clarify the README setup and usage instructions and document how to update the widget from Git.

## 1.0 — 2026-11-19

### Added

- Added a native KDE Plasma 6 system tray widget to mute individual audio sources in Steam recordings while keeping local playback audible.
- Added controls to hide and show sources and restore the full recording mix, along with German translations and install and uninstall scripts.

### Changed

- Audio sources use bundled category icons, and the mute and visibility controls use bundled SVG icons.
- Uninstallation restores the saved Steam recording connections before removing the widget, its preferences, session state, and Steam-specific icon cache. If restoration fails, uninstallation stops and keeps the recovery state.

### Fixed

- The widget stays open when launched from the system tray overflow while Steam is not recording.
- Audio restoration reconnects the original PipeWire links before removing the links created by the widget.
