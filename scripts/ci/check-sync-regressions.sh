#!/usr/bin/env bash
# Guard sync bridge invariants in the patch script and Rust backend.
# These patterns keep the Linux sync bridge wired into the Drive WebClients
# frontend correctly; regressions here silently break file sync.
set -euo pipefail

SYNC_PATCH="scripts/patch_drive_linux_sync_bridge.py"
FAIL=0

check_file() {
    local description="$1"
    local file="$2"
    local pattern="$3"
    if grep -qF "$pattern" "$file"; then
        echo "  ok  $description"
    else
        echo "  FAIL  $description"
        echo "        missing pattern in $file: $pattern"
        FAIL=1
    fi
}

echo "==> Sync bridge regression checks"

# Patch script must exist.
if [ ! -f "$SYNC_PATCH" ]; then
    echo "  FAIL  sync bridge patch script missing: $SYNC_PATCH"
    exit 1
fi
echo "  ok  sync bridge patch script exists"

# The component export must be present — if it's renamed the injection breaks.
check_file "ProtonDriveLinuxSyncBridge component exported" \
    "$SYNC_PATCH" "export const ProtonDriveLinuxSyncBridge"

# iterateDevices is the API used to enumerate Linux devices.
check_file "iterateDevices call present in bridge" \
    "$SYNC_PATCH" "iterateDevices"

# DeviceType.Linux filters to Linux-only devices — removing this exposes all devices.
check_file "DeviceType.Linux filter present in bridge" \
    "$SYNC_PATCH" "DeviceType.Linux"

# The patch must inject the bridge component into MainContainer.
check_file "MainContainer injection present in patch script" \
    "$SYNC_PATCH" "ProtonDriveLinuxSyncBridge />"

# The patch must reference the correct import path.
check_file "ProtonDriveLinuxSyncBridge import injection present" \
    "$SYNC_PATCH" "from './ProtonDriveLinuxSyncBridge'"

if [ "$FAIL" -ne 0 ]; then
    echo ""
    echo "Sync bridge invariant(s) missing — see failures above."
    exit 1
fi

echo "All sync bridge invariants intact."
