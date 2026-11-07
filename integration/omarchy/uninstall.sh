#!/usr/bin/env bash
# Remove the user-scoped Omarchy installation without deleting VoiceKey data.
set -euo pipefail
usage() {
  cat <<'HELP'
Usage: integration/omarchy/uninstall.sh [--purge-data]

Remove the VoiceKey user service, program, launcher and managed Omarchy
integration. Settings and downloaded models are retained by default.
  --purge-data  Also permanently delete the VoiceKey settings and models.
HELP
}
purge=0
while (($#)); do
  case "$1" in
    --purge-data) purge=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done
script_path=$(readlink -f -- "${BASH_SOURCE[0]}")
script_dir=$(cd -- "$(dirname -- "$script_path")" && pwd)
if [[ -d "$script_dir/assets/sounds" ]]; then
  sounds_source="$script_dir/assets/sounds"
  icon_source="$script_dir/assets/icon.png"
else
  repo_dir=$(cd -- "$script_dir/../.." && pwd)
  sounds_source="$repo_dir/app/src-tauri/resources/sounds"
  icon_source="$repo_dir/app/src-tauri/icons/128x128.png"
fi
config_dir=${XDG_CONFIG_HOME:-"$HOME/.config"}
state_dir="${XDG_STATE_HOME:-$HOME/.local/state}/voicekey"
app_data="${XDG_DATA_HOME:-$HOME/.local/share}/VoiceKey"
install_dir="$HOME/.local/share/voicekey"
bin_dir="$HOME/.local/bin"
menu_file="$config_dir/omarchy/extensions/omarchy-menu.jsonc"
backend_file="$config_dir/omarchy/defaults/dictation"
unit="$config_dir/systemd/user/voicekey.service"
[[ $config_dir = /* && $state_dir = /* && $app_data = /* ]] || { echo 'XDG paths must be absolute.' >&2; exit 1; }
for cmd in python3 systemctl flock; do
  command -v "$cmd" >/dev/null || { echo "Missing required command: $cmd" >&2; exit 1; }
done
case ":$PATH:" in *":$bin_dir:"*) ;; *) export PATH="$bin_dir:$PATH" ;; esac
# Reject invalid menu configuration before changing any installed component.
if [[ -f $menu_file ]]; then
  PYTHONDONTWRITEBYTECODE=1 python3 - "$script_dir/configure-menu.py" "$menu_file" <<'PYCODE'
import importlib.util, pathlib, sys
spec = importlib.util.spec_from_file_location('voicekey_menu', sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
m.remove(pathlib.Path(sys.argv[2]).read_text())
PYCODE
fi
previous=$(VOICEKEY_INSTALL_STATE="$state_dir/install.json" python3 - <<'PYCODE'
import json, os
try:
    value = json.load(open(os.environ['VOICEKEY_INSTALL_STATE'])).get('previous_backend', '')
    print(value if isinstance(value, str) else '')
except (OSError, ValueError, AttributeError):
    pass
PYCODE
)
service_managed=1
preserved_binary=0
if [[ -e $unit ]] && ! cmp -s "$unit" "$script_dir/voicekey.service"; then
  echo "VoiceKey service has been modified; preserve it and resolve it before uninstalling: $unit" >&2
  exit 1
fi

# Do not replace a backend the user selected after installing VoiceKey.
current=''
if [[ -f $backend_file ]]; then IFS= read -r current < "$backend_file" || true; fi
if [[ $current == voicekey && $service_managed == 1 ]]; then
  if [[ $previous =~ ^[a-z0-9][a-z0-9-]*$ && $previous != voicekey ]] \
     && command -v "$previous" >/dev/null && command -v "omarchy-dictation-$previous" >/dev/null \
     && command -v omarchy-dictation-use >/dev/null; then
    omarchy-dictation-use "$previous"
    echo "Restored previous dictation backend: $previous"
  else
    mkdir -p "$(dirname -- "$backend_file")"
    (
      flock -w 5 9 || { echo 'Dictation is busy; try again.' >&2; exit 1; }
      selected=''
      if [[ -f $backend_file ]]; then IFS= read -r selected < "$backend_file" || true; fi
      if [[ $selected == voicekey ]]; then rm -- "$backend_file"; fi
    ) 9> "$backend_file.lock"
    echo 'VoiceKey was the default. Select a new dictation backend in Omarchy settings if needed.'
  fi
fi

if ((service_managed)); then
  if [[ -e $unit ]]; then
    systemctl --user disable --now voicekey.service
    rm -- "$unit"
    systemctl --user daemon-reload
  fi
  # Only delete a later-modified executable when its saved installation hash matches.
  if [[ -f "$install_dir/voicekey" ]]; then
    if VOICEKEY_INSTALL_STATE="$state_dir/install.json" VOICEKEY_BINARY="$install_dir/voicekey" python3 - <<'PYCODE'
import hashlib, json, os
try:
    expected = json.load(open(os.environ['VOICEKEY_INSTALL_STATE'])).get('binary_sha256')
except (OSError, ValueError, AttributeError):
    expected = None
with open(os.environ['VOICEKEY_BINARY'], 'rb') as f:
    actual = hashlib.sha256(f.read()).hexdigest()
# Older installations have no manifest; this fixed path belongs to the installer.
raise SystemExit(0 if expected is None or expected == actual else 1)
PYCODE
    then rm -- "$install_dir/voicekey"
    else preserved_binary=1; echo "Preserving modified executable: $install_dir/voicekey" >&2
    fi
  fi
fi

remove_if_same() {
  local path=$1 expected=$2
  if [[ -f $path ]] && cmp -s "$path" "$expected"; then rm -- "$path"; fi
}
for name in omarchy-dictation-voicekey omarchy-install-dictation-voicekey; do
  remove_if_same "$bin_dir/$name" "$script_dir/$name"
done
if [[ -L "$bin_dir/voicekey" && $(readlink -- "$bin_dir/voicekey") == "$install_dir/voicekey" ]]; then
  rm -- "$bin_dir/voicekey"
fi
remove_if_same "$HOME/.local/share/icons/hicolor/128x128/apps/voicekey.png" "$icon_source"
for source in "$sounds_source"/*; do
  remove_if_same "$install_dir/resources/sounds/${source##*/}" "$source"
done
rmdir -- "$install_dir/resources/sounds" "$install_dir/resources" 2>/dev/null || true

# The launcher is generated from this exact template by install.sh.
desktop_file="$HOME/.local/share/applications/voicekey.desktop"
desktop_temp=$(mktemp)
trap 'rm -f -- "$desktop_temp"' EXIT
cat > "$desktop_temp" <<DESKTOP
[Desktop Entry]
Type=Application
Name=VoiceKey
Comment=Voice input settings
Exec=$install_dir/voicekey
Icon=voicekey
Categories=Utility;Audio;
StartupWMClass=voicekey
DESKTOP
remove_if_same "$desktop_file" "$desktop_temp"
python3 "$script_dir/configure-menu.py" "$menu_file" --remove
VOICEKEY_CONFIG_DIR="$config_dir" python3 - <<'PYCODE'
import os, pathlib, shutil, time
root = pathlib.Path(os.environ['VOICEKEY_CONFIG_DIR'])
blocks = {
    root / 'hypr/hyprland.lua': '\n-- VoiceKey overlay windows.\nrequire("hypr.voicekey")\n',
    root / 'voicekey/shortcuts.lua': '\n-- # VoiceKey: keep Alt+Space available for user bindings\n-- This runs after Omarchy defaults and before the user\'s own bindings.\nhl.unbind("ALT + SPACE")\n',
}
for path, block in blocks.items():
    if not path.is_file(): continue
    old = path.read_text()
    if block not in old: continue
    shutil.copy2(path, path.with_name(path.name + '.voicekey-backup-' + str(time.time_ns())))
    path.write_text(old.replace(block, '', 1))
PYCODE
# A pre-existing or user-edited require must never be left pointing at a
# deleted module. Leave the rules file if any reference remains.
if [[ ! -f "$config_dir/hypr/hyprland.lua" ]] || ! grep -Fq 'hypr.voicekey' "$config_dir/hypr/hyprland.lua"; then
  remove_if_same "$config_dir/hypr/voicekey.lua" "$script_dir/window-rules.lua"
else
  echo 'Preserving VoiceKey window rules because the Hyprland configuration still references them.' >&2
fi
# Remove only known uninstaller assets; unknown user-created files are untouched.
assets="$install_dir/uninstall-assets"
if [[ -L "$bin_dir/voicekey-uninstall" && $(readlink -- "$bin_dir/voicekey-uninstall") == "$assets/uninstall.sh" ]]; then
  rm -- "$bin_dir/voicekey-uninstall"
fi
for name in uninstall.sh configure-menu.py omarchy-dictation-voicekey omarchy-install-dictation-voicekey voicekey.service window-rules.lua; do
  remove_if_same "$assets/$name" "$script_dir/$name"
done
for source in "$sounds_source"/*; do
  remove_if_same "$assets/assets/sounds/${source##*/}" "$source"
done
remove_if_same "$assets/assets/icon.png" "$icon_source"
rmdir -- "$assets/assets/sounds" "$assets/assets" "$assets" "$install_dir" 2>/dev/null || true
if ((!preserved_binary)) && [[ -f "$state_dir/install.json" ]]; then rm -- "$state_dir/install.json"; fi
rmdir -- "$state_dir" 2>/dev/null || true
if ((purge)); then
  VOICEKEY_APP_DATA="$app_data" python3 - <<'PYCODE'
import os, pathlib, shutil
path = pathlib.Path(os.environ['VOICEKEY_APP_DATA'])
if path.is_symlink(): path.unlink()
elif path.is_dir(): shutil.rmtree(path)
PYCODE
  echo 'VoiceKey settings and models removed.'
else
  echo "VoiceKey settings and models preserved in $app_data"
fi
if command -v omarchy-menu >/dev/null; then omarchy-menu refresh; fi
if [[ -n ${HYPRLAND_INSTANCE_SIGNATURE:-} ]] && command -v hyprctl >/dev/null; then
  hyprctl reload >/dev/null
  errors=$(hyprctl configerrors)
  if [[ -n ${errors//[[:space:]]/} ]]; then printf 'Hyprland configuration errors:\n%s\n' "$errors" >&2; exit 1; fi
fi
echo 'VoiceKey uninstall complete.'
