#!/usr/bin/env bash
# Maintainer helper: regenerate the committed per-target seeds (mayhem/<target>/testsuite/) and the
# golden checksums used by mayhem/test.sh, from upstream's *.builder.xml files via the plain-flag
# <name>_generator binaries that mayhem/build.sh produces. Run inside the built image:
#   bash mayhem/gen_seeds.sh
set -euo pipefail
cd "${SRC:-/mayhem}"
python3 - <<'PY'
import glob, hashlib, os, subprocess, sys
sys.path.insert(0, "mayhem")
import build_fuzzers as b
rows = []
for name, plugin_dir, pattern in [(n, None, None) for n, _ in b.CORE] + [(n, d or n, None) for n, d, _ in b.PLUGINS]:
    tdir = f"plugins/{plugin_dir}/tests" if plugin_dir else "libfwupdplugin/tests"
    xmls = sorted(glob.glob(f"{tdir}/{name}*.builder.xml")) or [f"{tdir}/{name}.builder.xml"]
    seeds = f"mayhem/{name}_fuzzer/testsuite"
    for xml in xmls:
        out = f"/tmp/gen-{os.path.basename(xml)}.bin"
        subprocess.run([f"build/plain/bin/{name}_generator", xml, out], check=True)
        data = open(out, "rb").read()
        os.makedirs(seeds, exist_ok=True)
        open(f"{seeds}/{os.path.basename(xml).replace('.builder.xml', '.bin')}", "wb").write(data)
        rows.append((name, xml, hashlib.sha256(data).hexdigest()))
with open("mayhem/golden.tsv", "w") as f:
    for r in rows:
        f.write("\t".join(r) + "\n")
print(len(rows), "golden rows")
PY
