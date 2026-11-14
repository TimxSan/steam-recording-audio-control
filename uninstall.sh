#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
widget_id="org.cachy.steamaudiocontrol"
data_home="${XDG_DATA_HOME:-$HOME/.local/share}"
backend="$data_home/plasma/plasmoids/$widget_id/contents/scripts/bridge.py"
if [[ -f "$backend" ]] && command -v python3 >/dev/null 2>&1; then
  if ! reset_result="$(python3 "$backend" reset '' 0)"; then
    printf 'Warning: failed to restore audio routing. Check PipeWire connections.\n' >&2
  elif [[ "$reset_result" == *'"error":'* && "$reset_result" != *'"error":""'* ]]; then
    printf 'Warning: audio routing reported a problem during restore.\n' >&2
  fi
fi
if command -v qdbus6 >/dev/null 2>&1; then
  qdbus6 org.kde.plasmashell /PlasmaShell org.kde.PlasmaShell.evaluateScript "$(cat "$root/disable-tray.js")" >/dev/null 2>&1 || true
fi
if command -v kpackagetool6 >/dev/null 2>&1 && kpackagetool6 --type Plasma/Applet --show "$widget_id" >/dev/null 2>&1; then
  kpackagetool6 --type Plasma/Applet --remove "$widget_id"
fi
icon_home="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor"
rm -f -- "$icon_home/scalable/apps/$widget_id.svg"
if command -v kbuildsycoca6 >/dev/null 2>&1; then
  kbuildsycoca6 --noincremental >/dev/null 2>&1 || true
fi
if systemctl --user is-active --quiet plasma-plasmashell.service 2>/dev/null; then
  systemctl --user restart plasma-plasmashell.service || true
fi
printf 'Uninstalled Steam Recording Audio Control. Saved preferences were preserved.\n'
