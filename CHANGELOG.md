# Changelog

## Unreleased

- Added this changelog and documented how to keep it up to date.

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
