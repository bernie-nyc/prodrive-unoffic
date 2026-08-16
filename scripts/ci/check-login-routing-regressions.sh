#!/usr/bin/env bash
# Guard login and 2FA routing invariants in main.rs.
# These patterns are load-bearing; regressions here caused post-2FA freezes
# and Drive-not-loading bugs that are expensive to reproduce manually.
set -euo pipefail

MAIN_RS="src-tauri/src/main.rs"
FAIL=0

check() {
    local description="$1"
    local pattern="$2"
    if grep -qF "$pattern" "$MAIN_RS"; then
        echo "  ok  $description"
    else
        echo "  FAIL  $description"
        echo "        missing pattern: $pattern"
        FAIL=1
    fi
}

echo "==> Login/2FA routing regression checks"

# After successful login/2FA the account app redirects back to Drive.
check "account_login_complete_redirect_url handler present" \
    "account_login_complete_redirect_url"

# CAPTCHA flow: token must be extracted and re-attached to the auth retry.
check "captcha_completion_token handler present" \
    "captcha_completion_token"

# /login paths must be rewritten to /account/ so the local SSO app handles them.
check "/login rewrite to account app present" \
    'starts_with("/login")'

# Post-2FA Drive route restoration guard (regression from an earlier sprint).
check "post-2FA Drive route restoration guard present" \
    "Regression guard for post-2FA Drive load"

# store_login_credentials must exist to survive a CAPTCHA round-trip.
check "store_login_credentials command present" \
    "fn store_login_credentials"

# navigate_to_captcha must exist to redirect to the verification page.
check "navigate_to_captcha command present" \
    "fn navigate_to_captcha"

if [ "$FAIL" -ne 0 ]; then
    echo ""
    echo "Login/2FA routing invariant(s) missing — see failures above."
    exit 1
fi

echo "All login/2FA routing invariants intact."
