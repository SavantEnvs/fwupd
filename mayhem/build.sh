#!/usr/bin/env bash
# Builds every fwupd fuzz harness (sanitized, coverage-instrumented) plus their standalone
# reproducers, and the plain-flag generator binaries that mayhem/test.sh uses as its oracle.
# All dependencies (system -dev packages, the Rust toolchain) are baked into the image by
# mayhem/Dockerfile, so this script never touches the network and can be re-run on a built tree.
set -euo pipefail

[ -n "${SOURCE_DATE_EPOCH:-}" ] || unset SOURCE_DATE_EPOCH

: "${SANITIZER_FLAGS=-fsanitize=address,undefined -fno-sanitize-recover=all -fno-omit-frame-pointer}"
: "${DEBUG_FLAGS:=-g -gdwarf-3}"
: "${RUST_DEBUG_FLAGS:=-C debuginfo=2 -C force-frame-pointers=yes -C dwarf-version=3}"
: "${CC:=clang}"
: "${LIB_FUZZING_ENGINE:=-fsanitize=fuzzer}"
: "${MAYHEM_JOBS:=$(nproc)}"
: "${COVERAGE_FLAGS=}"
: "${SRC:=/mayhem}"
export SANITIZER_FLAGS DEBUG_FLAGS RUST_DEBUG_FLAGS CC LIB_FUZZING_ENGINE MAYHEM_JOBS COVERAGE_FLAGS SRC
: "${STANDALONE_FUZZ_MAIN:=/opt/mayhem/StandaloneFuzzTargetMain.c}"
export STANDALONE_FUZZ_MAIN
# Leak detection off at build time (linked into every fuzz and standalone binary)
export LSAN_OFF_SRC="$SRC/mayhem/lsan_off.c"

cd "$SRC"
python3 mayhem/build_fuzzers.py fuzz plain
