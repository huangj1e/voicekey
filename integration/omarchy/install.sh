#!/usr/bin/env bash
# Install VoiceKey for the current Omarchy user, including desktop integration.
set -euo pipefail

usage() {
  cat <<'HELP'
Usage: integration/omarchy/install.sh [--debug] [--binary PATH] [--no-activate]

Build and install VoiceKey for the current user, add the Omarchy menu and
window rules, and select it as the default dictation backend.
  --debug        Build the faster, unoptimized debug application.
  --binary PATH  Install an existing Tauri-built VoiceKey binary instead of building.
  --no-activate  Install files and settings without starting services or changing
                 the default backend (useful outside a running session).
HELP
}

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_dir=$(cd -- "$script_dir/../.." && pwd)
config_dir=${XDG_CONFIG_HOME:-"$HOME/.config"}
data_dir="$HOME/.local/share/voicekey"
bin_dir="$HOME/.local/bin"
mode=release
binary=''
activate=1
while (($#)); do
  case "$1" in
    --debug) mode=debug; shift ;;
    --binary) (($# >= 2)) || { usage >&2; exit 2; }; binary=$2; shift 2 ;;
    --no-activate) activate=0; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done
[[ $config_dir = /* ]] || { echo 'XDG_CONFIG_HOME must be an absolute path.' >&2; exit 1; }
[[ -f "$config_dir/hypr/hyprland.lua" ]] || { echo 'Omarchy Hyprland configuration not found.' >&2; exit 1; }
for cmd in python3 install wtype; do
  command -v "$cmd" >/dev/null || { echo "Missing required command: $cmd" >&2; exit 1; }
done
if ((activate)); then
  for cmd in systemctl omarchy-dictation-use omarchy-restart-hyprctl omarchy-menu; do
    command -v "$cmd" >/dev/null || { echo "Missing Omarchy dependency: $cmd" >&2; exit 1; }
  done
  [[ -n ${XDG_RUNTIME_DIR:-} ]] || { echo 'A running graphical user session is required; use --no-activate to install without one.' >&2; exit 1; }
fi

if [[ -z $binary ]]; then
  for cmd in cargo rustc cmake npm pkg-config; do
    command -v "$cmd" >/dev/null || { echo "Missing build dependency: $cmd" >&2; exit 1; }
  done
  for pkg in gtk+-3.0 webkit2gtk-4.1 alsa; do
    pkg-config --exists "$pkg" || { echo "Missing system development library: $pkg" >&2; exit 1; }
  done
  (cd "$repo_dir/app" && npm ci && if [[ $mode == debug ]]; then npm run tauri build -- --debug --no-bundle; else npm run tauri build -- --no-bundle; fi)
  binary="$repo_dir/target/$mode/voicekey"
fi
[[ -f $binary && -x $binary ]] || { echo "VoiceKey binary not found or not executable: $binary" >&2; exit 1; }
# Validate the menu before changing installed files or stopping an existing service.
PYTHONDONTWRITEBYTECODE=1 python3 - "$script_dir/configure-menu.py" "$config_dir/omarchy/extensions/omarchy-menu.jsonc" <<'PY'
import importlib.util, pathlib, sys
spec = importlib.util.spec_from_file_location('voicekey_menu', sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
p = pathlib.Path(sys.argv[2]); m.update(p.read_text() if p.exists() else '{}\n')
PY

backup() {
  local path=$1
  if [[ -e $path || -L $path ]]; then
    cp -aL -- "$path" "$path.voicekey-backup-$(date +%s%N)"
  fi
}
install_config() {
  local source=$1 dest=$2
  mkdir -p -- "$(dirname -- "$dest")"
  if [[ -e $dest ]] && cmp -s -- "$source" "$dest"; then return; fi
  backup "$dest"
  install -m 644 -- "$source" "$dest"
}
append_once() {
  local path=$1 marker=$2 content=$3
  mkdir -p -- "$(dirname -- "$path")"
  if [[ -f $path ]] && grep -Fq -- "$marker" "$path"; then return; fi
  backup "$path"
  printf '\n%s\n' "$content" >> "$path"
}

if ((activate)) && systemctl --user is-active --quiet voicekey.service; then
  systemctl --user stop voicekey.service
fi
mkdir -p -- "$data_dir/resources/sounds" "$bin_dir" "$HOME/.local/share/applications" "$HOME/.local/share/icons/hicolor/128x128/apps" "$config_dir/systemd/user"
if [[ ! -e "$data_dir/voicekey" || ! $binary -ef "$data_dir/voicekey" ]]; then
  install -m 755 -- "$binary" "$data_dir/voicekey"
fi
install -m 644 -- "$repo_dir"/app/src-tauri/resources/sounds/* "$data_dir/resources/sounds/"
install -m 644 -- "$repo_dir/app/src-tauri/icons/128x128.png" "$HOME/.local/share/icons/hicolor/128x128/apps/voicekey.png"
for name in omarchy-dictation-voicekey omarchy-install-dictation-voicekey; do
  if [[ -e "$bin_dir/$name" ]] && ! cmp -s "$script_dir/$name" "$bin_dir/$name"; then backup "$bin_dir/$name"; fi
  install -m 755 -- "$script_dir/$name" "$bin_dir/$name"
done
if [[ -e "$bin_dir/voicekey" || -L "$bin_dir/voicekey" ]]; then
  if [[ $(readlink -- "$bin_dir/voicekey" || true) != "$data_dir/voicekey" ]]; then backup "$bin_dir/voicekey"; fi
fi
ln -sfn -- "$data_dir/voicekey" "$bin_dir/voicekey"
desktop_file="$HOME/.local/share/applications/voicekey.desktop"
desktop_temp=$(mktemp)
trap 'rm -f -- "$desktop_temp"' EXIT
cat > "$desktop_temp" <<DESKTOP
[Desktop Entry]
Type=Application
Name=VoiceKey
Comment=Voice input settings
Exec=$data_dir/voicekey
Icon=voicekey
Categories=Utility;Audio;
StartupWMClass=voicekey
DESKTOP
if [[ ! -e $desktop_file ]] || ! cmp -s "$desktop_temp" "$desktop_file"; then
  backup "$desktop_file"
  install -m 644 -- "$desktop_temp" "$desktop_file"
fi
install_config "$script_dir/voicekey.service" "$config_dir/systemd/user/voicekey.service"
install_config "$script_dir/window-rules.lua" "$config_dir/hypr/voicekey.lua"
append_once "$config_dir/hypr/hyprland.lua" 'require("hypr.voicekey")' $'-- VoiceKey overlay windows.\nrequire("hypr.voicekey")'
append_once "$config_dir/voicekey/shortcuts.lua" '# VoiceKey: keep Alt+Space available for user bindings' $'-- # VoiceKey: keep Alt+Space available for user bindings\n-- This runs after Omarchy defaults and before the user\x27s own bindings.\nhl.unbind("ALT + SPACE")'
python3 "$script_dir/configure-menu.py" "$config_dir/omarchy/extensions/omarchy-menu.jsonc"

if ((activate)); then
  systemctl --user daemon-reload
  # Keep ~/.local/bin reachable in user sessions even when it was absent at login.
  case ":$PATH:" in *":$bin_dir:"*) ;; *) export PATH="$bin_dir:$PATH" ;; esac
  "$bin_dir/omarchy-install-dictation-voicekey"
  omarchy-menu refresh
  if [[ -n ${HYPRLAND_INSTANCE_SIGNATURE:-} ]]; then
    hyprctl reload >/dev/null
    errors=$(hyprctl configerrors)
    if [[ -n ${errors//[[:space:]]/} ]]; then
      printf 'Hyprland configuration errors:\n%s\n' "$errors" >&2
      exit 1
    fi
  fi
else
  echo 'Installed files only. To activate in a graphical session, rerun without --no-activate.'
fi
if ! find /dev/input/by-path -maxdepth 1 -name '*-event-kbd' -readable -print -quit 2>/dev/null | grep -q .; then
  echo 'Note: no readable keyboard event device was found; custom shortcuts and candidate keys may require input-device permissions.' >&2
fi
echo "VoiceKey installed in $data_dir"
