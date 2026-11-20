#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
widget_id="org.cachy.steamaudiocontrol"
for dependency in kpackagetool6 pw-dump pw-link pw-cli python3; do
  if ! command -v "$dependency" >/dev/null 2>&1; then
    printf 'Missing required command: %s\n' "$dependency" >&2
    exit 1
  fi
done

package_dir="$root/plasmoid"
if [[ -e "$root/.git" ]]; then
  # Keep local artifacts out of the package copied by KPackage.
  staging_dir="$(mktemp -d)"
  trap 'rm -rf -- "$staging_dir"' EXIT
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
mkdir -p "$icon_dir"
install -m 644 "$package_dir/contents/icons/steam-audio-control.svg" "$icon_dir/$widget_id.svg"

if kpackagetool6 --type Plasma/Applet --show "$widget_id" >/dev/null 2>&1; then
  kpackagetool6 --type Plasma/Applet --upgrade "$package_dir"
else
  kpackagetool6 --type Plasma/Applet --install "$package_dir"
fi

rm -rf -- "$data_home/stream-audio-control/$widget_id-fallback-icons"

if command -v qdbus6 >/dev/null 2>&1; then
  qdbus6 org.kde.plasmashell /PlasmaShell org.kde.PlasmaShell.evaluateScript "$(cat "$root/enable-tray.js")" >/dev/null 2>&1 || true
fi

legacy="$HOME/.config/autostart/steam-audio-control.desktop"
if [[ -f "$legacy" ]]; then
  mv -f -- "$legacy" "$legacy.disabled"
fi
shortcut="$HOME/.local/share/applications/steam-audio-control.desktop"
if [[ -f "$shortcut" ]] && grep -Fq '.local/bin/steam-audio-control' "$shortcut"; then
  rm -f -- "$shortcut"
fi

if command -v kbuildsycoca6 >/dev/null 2>&1; then
  kbuildsycoca6 --noincremental >/dev/null 2>&1 || true
fi
if systemctl --user is-active --quiet plasma-plasmashell.service 2>/dev/null; then
  systemctl --user restart plasma-plasmashell.service || true
fi
printf 'Installed Steam Recording Audio Control.\n'
printf 'Set its visibility to "Shown When Relevant" in System Tray Settings > Entries.\n'
