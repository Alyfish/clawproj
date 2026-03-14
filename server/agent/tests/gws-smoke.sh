#!/usr/bin/env bash
set -uo pipefail

# gws CLI smoke test — verifies binary installation and command structure
# Run inside the agent container: docker exec clawbot-agent bash /app/server/agent/tests/gws-smoke.sh

PASS=0
FAIL=0

check() {
    local desc="$1"; shift
    if "$@" >/dev/null 2>&1; then
        echo "  PASS: $desc"
        PASS=$((PASS + 1))
    else
        echo "  FAIL: $desc"
        FAIL=$((FAIL + 1))
    fi
}

echo "=== gws CLI Smoke Test ==="

# 1. Binary exists and runs
check "gws binary on PATH" which gws
check "gws --version" gws --version

# 2. Can parse a service (Drive)
check "gws drive --help" gws drive --help

# 3. Dry-run confirms command structure + env var reading
#    gws --dry-run outputs the HTTP request it WOULD make as JSON
DRYRUN_OUTPUT=$(GOOGLE_WORKSPACE_CLI_TOKEN=smoke-test-token \
    gws drive files list --params '{"pageSize":1}' --dry-run 2>&1) || true

if echo "$DRYRUN_OUTPUT" | grep -q '"dry_run"'; then
    echo "  PASS: dry-run outputs request structure"
    PASS=$((PASS + 1))
else
    echo "  FAIL: dry-run did not output expected JSON (got: $DRYRUN_OUTPUT)"
    FAIL=$((FAIL + 1))
fi

echo ""
echo "Results: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
