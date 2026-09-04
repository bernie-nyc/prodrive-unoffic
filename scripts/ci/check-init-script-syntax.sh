#!/usr/bin/env bash
# Syntax-check the JavaScript that src-tauri/src/main.rs injects into the WebView.
#
# The init script installs the fetch/XHR proxy that routes every Proton API call
# through Rust. A single syntax error anywhere in it (an unterminated string, a
# stray brace) makes WebKit reject the whole script silently: no proxy, no
# console forwarding, and login fails with "cannot fetch server time". That
# exact failure shipped in several builds before this gate existed.
#
# The script body is delimited in main.rs by two JS comment markers; we extract
# it, wrap it in the same IIFE main.rs uses, and let node parse it.
set -euo pipefail

MAIN_RS="src-tauri/src/main.rs"
BEGIN_MARKER='// __INIT_SCRIPT_JS_BEGIN__'
END_MARKER='// __INIT_SCRIPT_JS_END__'

echo "==> WebView init script syntax check"

if ! command -v node >/dev/null 2>&1; then
    echo "  FAIL  node is required to parse the init script"
    exit 1
fi

if ! grep -qF "$BEGIN_MARKER" "$MAIN_RS" || ! grep -qF "$END_MARKER" "$MAIN_RS"; then
    echo "  FAIL  init script markers not found in $MAIN_RS"
    echo "        expected '$BEGIN_MARKER' and '$END_MARKER'"
    exit 1
fi

TMP_JS="$(mktemp --suffix=.js)"
trap 'rm -f "$TMP_JS"' EXIT

{
    echo '(function () {'
    # Stand-in for the distro-specific worker shim that precedes the marker.
    echo 'window.Worker = undefined; window.SharedWorker = undefined;'
    awk -v b="$BEGIN_MARKER" -v e="$END_MARKER" \
        'index($0, b) { inside = 1; next } index($0, e) { inside = 0 } inside' \
        "$MAIN_RS"
    echo '})();'
} > "$TMP_JS"

LINE_COUNT="$(wc -l < "$TMP_JS")"
if [ "$LINE_COUNT" -lt 100 ]; then
    echo "  FAIL  extracted only $LINE_COUNT lines; are the markers misplaced?"
    exit 1
fi

if ! node --check "$TMP_JS"; then
    echo "  FAIL  init script does not parse (see error above)"
    exit 1
fi

echo "  ok  init script parses ($LINE_COUNT lines)"
