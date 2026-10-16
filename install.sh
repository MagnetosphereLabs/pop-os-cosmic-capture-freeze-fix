#!/bin/bash
set -euo pipefail

installer_url='https://raw.githubusercontent.com/MagnetosphereLabs/pop-os-cosmic-capture-freeze-fix/v1.0.0/install.py'
installer_sha256='0b652dfd29ae396048092d4c6896695fcf7e9ce65394272a99782a5bef5caac5'
work_dir="$(/usr/bin/mktemp -d)"
trap '/usr/bin/rm -rf -- "$work_dir"' EXIT

/usr/bin/curl --fail --silent --show-error --location \
    --proto '=https' --tlsv1.2 --max-time 120 \
    "$installer_url" --output "$work_dir/install.py"
printf '%s  %s\n' "$installer_sha256" "$work_dir/install.py" | /usr/bin/sha256sum --check --status
/usr/bin/python3 "$work_dir/install.py" "$@"
