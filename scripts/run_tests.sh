#!/usr/bin/env bash
# Run the RoboCommand host monitor + report.py test suite.
# PYTHON overrides the interpreter (it needs protobuf >= the vendored gencode).
set -uo pipefail

cd "$(dirname "$0")/.."
PY="${PYTHON:-python3}"
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-offscreen}"

rc=0
for t in tests/test_course_validation.py tests/test_fleet_state.py tests/test_console.py \
         tests/test_report.py tests/test_host_loopback.py tests/test_live_broker.py; do
    echo ""
    echo "########## $t ##########"
    if ! "$PY" "$t"; then
        rc=1
    fi
done

echo ""
if [ "$rc" -eq 0 ]; then
    echo "TEST SUITE PASSED"
else
    echo "TEST SUITE FAILED"
fi
exit "$rc"
