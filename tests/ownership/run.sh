#!/bin/bash
# Builds the synthetic-boundary ownership harness against a source tree with
# ASan/UBSan and runs every test in its own process (macOS only).
#
#   tests/ownership/run.sh <source-root> <fixed|baseline>
#
# <source-root> provides the plugin sources, the helper sources and the
# bundled 4D Plugin API. The harness itself always comes from this script's
# directory, so the SAME harness can be run against an immutable baseline
# (git archive of the base SHA) and against the fixed tree.
#
# In "fixed" mode every test must pass. In "baseline" mode the tests named
# in EXPECTED_BASELINE_FAILURES must fail and every other test (guards and
# controls) must pass; anything else is a harness or model error.
#
# No camera or scanner is touched: PluginMain is never called, so the
# ImageCaptureCore device browser is never started.
set -euo pipefail

SRC=$(cd "$1" && pwd)
MODE=$2
HERE=$(cd "$(dirname "$0")" && pwd)
OUT=$(mktemp -d)
trap 'rm -rf "$OUT"' EXIT

EXPECTED_BASELINE_FAILURES="
defect_byid_param_owner_leak
defect_1007_param_owner_leak
defect_byid_result_not_cleared
defect_ob_set_s_owner_leak
defect_ob_set_a_owner_leak
defect_ob_set_p_owner_leak
defect_ob_get_a_result_not_cleared
defect_ob_get_b_wrong_kind_not_cleared
defect_ob_get_n_wrong_kind_not_cleared
defect_ob_get_c_wrong_kind_not_cleared
defect_ob_get_o_wrong_kind_not_cleared
"

SAN="-g -O1 -fno-omit-frame-pointer -fsanitize=address,undefined -fno-sanitize-recover=undefined"
API="$SRC/4D Plugin API"
# Same header search paths as the Xcode target (no prefix header).
INC=(-I "$API" -I "$API/Classes" -I "$SRC" -I "$SRC/support" -I "$SRC/include" -I "$SRC/include/json")

objs=()
cc() { # <lang> <file> [extra flags...]
    local lang=$1 file=$2; shift 2
    local o="$OUT/$(basename "$file").o"
    xcrun clang $SAN -w -x "$lang" "$@" -c "$file" -o "$o"
    objs+=("$o")
}

cc objective-c++ "$API/4DPluginAPI.c" "${INC[@]}" -std=c++17
for f in "$API"/Classes/*.cpp; do
    cc objective-c++ "$f" "${INC[@]}" -std=c++17 -fno-objc-arc
done
cc objective-c++ "$SRC/support/4DPlugin-JSON.cpp" "${INC[@]}" -std=c++17
cc objective-c++ "$SRC/4DPlugin-ImageCaptureCore.cpp" "${INC[@]}" -std=c++17 -fno-objc-arc
cc objective-c++ "$HERE/engine_harness.mm" "${INC[@]}" -std=c++17 -fno-objc-arc

# ImageCaptureCore is linked only because the plugin source references its
# classes; nothing in the harness instantiates a device browser or device.
xcrun clang++ $SAN "${objs[@]}" "$SRC/a/libjsoncpp.a" \
    -framework Foundation -framework CoreFoundation -framework Cocoa -framework ImageCaptureCore \
    -o "$OUT/harness"

export ASAN_OPTIONS=abort_on_error=0:halt_on_error=1
export UBSAN_OPTIONS=print_stacktrace=1:halt_on_error=1

bad=0
for t in $("$OUT/harness" --list); do
    if "$OUT/harness" "$t" >"$OUT/$t.log" 2>&1; then got=pass; else got=fail; fi
    expect=pass
    if [ "$MODE" = baseline ] && grep -qx "$t" <<<"$EXPECTED_BASELINE_FAILURES"; then expect=fail; fi
    if [ "$got" = "$expect" ]; then status=OK; else status=UNEXPECTED; bad=1; fi
    printf '%-12s %-5s (expected %-4s) %s\n' "$status" "$got" "$expect" "$t"
    if [ "$got" = fail ]; then sed 's/^/    | /' "$OUT/$t.log"; fi
    # A sanitizer report or engine violation is never an expected outcome.
    if grep -qE 'ERROR: AddressSanitizer|runtime error:|ENGINE VIOLATION' "$OUT/$t.log"; then
        echo "UNEXPECTED   sanitizer/engine violation in $t"; bad=1
    fi
done

if [ $bad -ne 0 ]; then echo "RESULT ($MODE): FAILED"; exit 1; fi
echo "RESULT ($MODE): all outcomes as expected"
