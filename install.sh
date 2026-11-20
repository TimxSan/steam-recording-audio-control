#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
widget_id="org.cachy.steamaudiocontrol"
for dependency in kpackagetool6 pw-dump pw-link pw-cli python3 timeout; do
  if ! command -v "$dependency" >/dev/null 2>&1; then
    printf 'Missing required command: %s\n' "$dependency" >&2
    exit 1
  fi
done

package_dir="$root/plasmoid"
bridge="$package_dir/contents/scripts/bridge.py"
staging_dir=""
audio_suspended=false
cleanup() {
  status=$?
  trap - EXIT
  if "$audio_suspended" && ! python3 -B "$bridge" resume >/dev/null; then
    status=1
  fi
  if [[ -n "$staging_dir" ]]; then
    rm -rf -- "$staging_dir"
  fi
  exit "$status"
}
trap cleanup EXIT

if [[ -e "$root/.git" ]]; then
  staging_dir="$(mktemp -d)"
  (
    cd -- "$root"
    git ls-files -z --cached --deduplicate -- plasmoid/ |
      while IFS= read -r -d '' package_file; do
        if [[ -f "$package_file" || -L "$package_file" ]]; then
          cp -P --parents -- "$package_file" "$staging_dir"
        fi
      done
  )
  package_dir="$staging_dir/plasmoid"
fi

data_home="${XDG_DATA_HOME:-$HOME/.local/share}"
icon_dir="$data_home/icons/hicolor/scalable/apps"

if systemctl --user is-active --quiet plasma-plasmashell.service 2>/dev/null; then
  python3 -B "$bridge" restore --suspend >/dev/null
  audio_suspended=true
fi

package_root="$data_home/plasma/plasmoids"
mkdir -p "$package_root"
if [[ -e "$package_root/$widget_id" || -L "$package_root/$widget_id" ]]; then
  kpackagetool6 --type Plasma/Applet --packageroot "$package_root" --upgrade "$package_dir"
else
  kpackagetool6 --type Plasma/Applet --packageroot "$package_root" --install "$package_dir"
fi

mkdir -p "$icon_dir"
install -m 644 "$package_dir/contents/icons/steam-audio-control.svg" "$icon_dir/$widget_id.svg"
rm -rf -- "$data_home/stream-audio-control/$widget_id-fallback-icons"

if command -v qdbus6 >/dev/null 2>&1; then
  qdbus6 org.kde.plasmashell /PlasmaShell org.kde.PlasmaShell.evaluateScript "$(cat "$root/enable-tray.js")" >/dev/null 2>&1 || true
fi

if command -v kbuildsycoca6 >/dev/null 2>&1; then
  kbuildsycoca6 --noincremental >/dev/null 2>&1 || true
fi
if "$audio_suspended"; then
  python3 -B "$bridge" restore --suspend >/dev/null
  systemctl --user restart plasma-plasmashell.service
fi
python3 -B "$bridge" resume >/dev/null
audio_suspended=false
printf 'Installed Steam Recording Audio Control.\n'
printf 'Set its visibility to "Shown When Relevant" in System Tray Settings > Entries.\n'
