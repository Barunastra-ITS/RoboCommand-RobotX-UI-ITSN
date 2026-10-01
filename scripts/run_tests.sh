#!/usr/bin/env bash
# Run the RoboCommand UI test suite against a throwaway local broker.
set -uo pipefail

cd "$(dirname "$0")/.."

rc=0

# Standalone unit tests first (no broker needed)
if ! python3 tests/test_course_validation.py; then
    rc=1
fi

# Integration suites start their own throwaway broker on 18830
for t in tests/test_ui_integration.py tests/test_robustness.py; do
    echo ""
    echo "########## $t ##########"
    if ! python3 "$t"; then
        rc=1
    fi
done

# Compose-stack suite needs the documented broker on 1883.
if ss -ltn 2>/dev/null | grep -q ':1883 '; then
    echo ""
    echo "########## tests/test_compose_stack.py ##########"
    if ! python3 tests/test_compose_stack.py; then
        rc=1
    fi
else
    echo ""
    echo "Skipping tests/test_compose_stack.py (no broker on :1883)."
    echo "Start it with:"
    echo "  docker compose -f robocommand/RobotX_2026/docker-compose.yml up -d broker"
fi

echo ""
if [ "$rc" -eq 0 ]; then
    echo "TEST SUITE PASSED"
else
    echo "TEST SUITE FAILED"
fi
exit "$rc"