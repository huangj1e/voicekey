#!/usr/bin/env bash
# Create a self-contained Omarchy installer archive around a Tauri Linux binary.
set -euo pipefail
if (($# != 3)); then
  echo "Usage: $0 VERSION BINARY OUTPUT.tar.gz" >&2
  exit 2
fi
version=$1
binary=$2
output=$3
[[ $version =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo 'Invalid release version.' >&2; exit 1; }
[[ -f $binary && -x $binary ]] || { echo 'Built application not found.' >&2; exit 1; }
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_dir=$(cd -- "$script_dir/../.." && pwd)
mkdir -p -- "$(dirname -- "$output")"
output=$(realpath -m -- "$output")
tmp=$(mktemp -d)
trap 'rm -rf -- "$tmp"' EXIT
root="$tmp/VoiceKey-$version-linux-x86_64"
mkdir -p "$root/app/src-tauri/resources" "$root/app/src-tauri/icons" "$root/integration/omarchy"
install -m 755 "$binary" "$root/voicekey"
cp -a "$repo_dir/app/src-tauri/resources/sounds" "$root/app/src-tauri/resources/"
install -m 644 "$repo_dir/app/src-tauri/icons/128x128.png" "$root/app/src-tauri/icons/128x128.png"
for name in install.sh uninstall.sh configure-menu.py omarchy-dictation-voicekey omarchy-install-dictation-voicekey; do
  install -m 755 "$script_dir/$name" "$root/integration/omarchy/$name"
done
for name in menu.jsonc shortcuts.lua voicekey.service window-rules.lua; do
  install -m 644 "$script_dir/$name" "$root/integration/omarchy/$name"
done
cat > "$root/install.sh" <<'INSTALL'
#!/usr/bin/env bash
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
exec "$root/integration/omarchy/install.sh" --binary "$root/voicekey" "$@"
INSTALL
chmod 755 "$root/install.sh"
cat > "$root/README.txt" <<'README'
VoiceKey for x86_64 Linux / Omarchy

Extract the archive, open a terminal in this directory inside your Omarchy
graphical session, and run:

    ./install.sh

This installs VoiceKey for the current user, adds its Omarchy integration,
and selects it as the default dictation backend. Existing dictation software
is not removed. Runtime requirements include wtype, Python 3, GTK 3,
WebKitGTK 4.1, ALSA, and the Omarchy tools. The wtype virtual keyboard
requires a compatible Wayland compositor. The current user needs read access
to keyboard event devices for candidate selection and custom shortcuts.

To remove the application later, run voicekey-uninstall. Settings and models
are kept unless you explicitly pass --purge-data.
README
tar -C "$tmp" -czf "$output" "${root##*/}"
echo "Created $output"
