#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
widget_id="org.cachy.steamaudiocontrol"
data_home="${XDG_DATA_HOME:-$HOME/.local/share}"
config_dir="$HOME/.config/steam-audio-control"
state_dir="$HOME/.local/state/steam-audio-control-native"
package_root="$data_home/plasma/plasmoids"
bridge="$root/plasmoid/contents/scripts/bridge.py"
if ! python3 -B "$bridge" restore --suspend >/dev/null; then
  printf 'Could not restore Steam recording audio. Uninstallation stopped and the recovery state was kept.\n' >&2
  exit 1
fi
if [[ -e "$package_root/$widget_id" || -L "$package_root/$widget_id" ]]; then
  if ! kpackagetool6 --type Plasma/Applet --packageroot "$package_root" --remove "$widget_id"; then
    python3 -B "$bridge" resume >/dev/null
    exit 1
  fi
fi
if command -v qdbus6 >/dev/null 2>&1; then
  qdbus6 org.kde.plasmashell /PlasmaShell org.kde.PlasmaShell.evaluateScript "$(cat "$root/disable-tray.js")" >/dev/null 2>&1 || true
fi
if systemctl --user is-active --quiet plasma-plasmashell.service 2>/dev/null; then
  systemctl --user restart plasma-plasmashell.service || true
fi
if ! python3 -B "$bridge" restore --suspend >/dev/null; then
  printf 'Could not finish restoring Steam recording audio. Recovery state and preferences were kept.\n' >&2
  exit 1
fi
icon_home="$data_home/icons/hicolor"
rm -f -- "$icon_home/scalable/apps/$widget_id.svg"
rm -rf -- "$data_home/stream-audio-control/$widget_id-fallback-icons"
if command -v kbuildsycoca6 >/dev/null 2>&1; then
  kbuildsycoca6 --noincremental >/dev/null 2>&1 || true
fi
rm -f -- "$config_dir/settings.json" "$config_dir/settings.json.tmp" \
  "$state_dir/session.json" "$state_dir/session.json.tmp" "$state_dir/bridge.lock"
rmdir -- "$config_dir" "$state_dir" 2>/dev/null || true
printf 'Uninstalled Steam Recording Audio Control and removed its settings and cache.\n'
