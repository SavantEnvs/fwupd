#!/usr/bin/env bash
#
# Functional oracle: for every format fwupd can fuzz, build a firmware image from upstream's own
# *.builder.xml with the plain-flag <name>_generator that mayhem/build.sh produced, and require the
# exact bytes recorded in mayhem/golden.tsv (sha256). A neutered or broken parser/serializer produces
# no output or different bytes and fails. Run `bash mayhem/gen_seeds.sh` to refresh the golden file
# after an intentional upstream change.
set -uo pipefail
[ -n "${SOURCE_DATE_EPOCH:-}" ] || unset SOURCE_DATE_EPOCH
: "${SRC:=/mayhem}"
cd "$SRC"

emit_ctrf() {
  local tool="$1" passed="$2" failed="$3" skipped="${4:-0}" pending="${5:-0}" other="${6:-0}"
  local tests=$(( passed + failed + skipped + pending + other ))
  cat > "${CTRF_REPORT:-$SRC/ctrf-report.json}" <<JSON
{
  "results": {
    "tool": { "name": "$tool" },
    "summary": {
      "tests": $tests,
      "passed": $passed,
      "failed": $failed,
      "pending": $pending,
      "skipped": $skipped,
      "other": $other
    }
  }
}
JSON
  printf 'CTRF {"results":{"tool":{"name":"%s"},"summary":{"tests":%d,"passed":%d,"failed":%d,"pending":%d,"skipped":%d,"other":%d}}}\n' \
    "$tool" "$tests" "$passed" "$failed" "$pending" "$skipped" "$other"
  [ "$failed" -eq 0 ]
}

bindir=build/plain/bin
[ -d "$bindir" ] || { echo "missing $bindir — mayhem/build.sh did not build the generators" >&2; emit_ctrf golden-sha256 0 1; exit 1; }
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

passed=0; failed=0
while IFS=$'\t' read -r name xml want; do
  out="$tmp/$(basename "$xml" .builder.xml).bin"
  rm -f "$out"
  if [ -x "$bindir/${name}_generator" ] && "$bindir/${name}_generator" "$xml" "$out" >"$tmp/log" 2>&1 && [ -s "$out" ]; then
    got="$(sha256sum "$out" | cut -d' ' -f1)"
  else
    got="<no output>"
  fi
  if [ "$got" = "$want" ]; then
    passed=$((passed + 1))
  else
    failed=$((failed + 1)); echo "FAIL $name $xml: got $got want $want" >&2
  fi
done < mayhem/golden.tsv

emit_ctrf golden-sha256 "$passed" "$failed"
