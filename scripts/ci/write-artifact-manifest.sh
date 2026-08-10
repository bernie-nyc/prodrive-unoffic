#!/bin/bash
# write-artifact-manifest.sh — Write a JSON metadata file alongside a build artifact.
#
# Usage:
#   ARTIFACT_MANIFEST_DIR=<dir> bash write-artifact-manifest.sh \
#     <artifact-name> <pkg-type> <target> <arch> <file-glob>
#
# Arguments:
#   artifact-name  CI artifact name (e.g. deb-package-debian12)
#   pkg-type       Package format: deb, source, …
#   target         Distro/OS target: debian-12, source, …
#   arch           CPU architecture: x86_64, all, …
#   file-glob      Shell glob matching the package file(s) to include
#
# Environment:
#   ARTIFACT_MANIFEST_DIR  Directory to write the manifest into (default: .)
set -euo pipefail

ARTIFACT_NAME="${1:?artifact-name required}"
PKG_TYPE="${2:?pkg-type required}"
TARGET="${3:?target required}"
ARCH="${4:?arch required}"
FILE_GLOB="${5:?file-glob required}"

OUTPUT_DIR="${ARTIFACT_MANIFEST_DIR:-.}"
mkdir -p "$OUTPUT_DIR"

# Resolve glob to a newline-separated list of basenames (may be empty before build)
FILES=""
while IFS= read -r -d $'\0' f; do
    FILES+="$(basename "$f")"$'\n'
done < <(eval "ls -1 $FILE_GLOB 2>/dev/null" | tr '\n' '\0' || true)

FILES_JSON=$(printf '%s' "$FILES" | python3 -c "
import json, sys
names = [l for l in sys.stdin.read().splitlines() if l]
print(json.dumps(names))
")

cat > "${OUTPUT_DIR}/${ARTIFACT_NAME}.json" << EOF
{
  "artifact": "${ARTIFACT_NAME}",
  "type": "${PKG_TYPE}",
  "target": "${TARGET}",
  "arch": "${ARCH}",
  "files": ${FILES_JSON}
}
EOF

echo "  ✓ Wrote ${OUTPUT_DIR}/${ARTIFACT_NAME}.json"
