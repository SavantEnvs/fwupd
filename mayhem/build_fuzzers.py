#!/usr/bin/env python3
# Builds fwupd's libFuzzer harnesses the way upstream's contrib/ci/oss-fuzz.py does (same source
# list, same fu-fuzzer-firmware.c.in template), but against the image's system glib/libxmlb/libusb
# so it needs no network. Two flavours are built from the same sources:
#   fuzz  -> sanitized, coverage-instrumented objects; /mayhem/<name>_fuzzer and <name>_fuzzer-standalone
#   plain -> normal flags; build/plain/bin/<name>_generator (used by mayhem/test.sh as the oracle)
import concurrent.futures
import glob
import os
import shlex
import shutil
import subprocess
import sys

SRC = os.environ.get("SRC", "/mayhem")
BUILD = os.path.join(SRC, "build")
JOBS = int(os.environ.get("MAYHEM_JOBS") or os.cpu_count() or 4)

CORE = [
    ("csv", None), ("cab", None), ("coswid", None), ("dfuse", None), ("edid", "edid"),
    ("elf", None), ("fdt", None), ("fit", None), ("fmap", None),
    ("hid-descriptor", "hid-descriptor"), ("ihex", None), ("pefile", None), ("srec", None),
    ("intel-thunderbolt", None), ("ifwi-cpd", None), ("ifwi-fpt", None), ("json", None),
    ("oprom", None), ("protobuf", "protobuf"), ("uswid", None), ("usb-device", "usb-device"),
    ("efi-filesystem", "efi-filesystem"), ("efi-volume", "efi-volume"),
    ("efi-load-option", "efi-load-option"), ("ifd", None), ("ifd-bios", "ifd-bios"),
    ("tpm-eventlog-v1", "tpm-eventlog-v1"), ("tpm-eventlog-v2", "tpm-eventlog-v2"), ("zip", None),
]
# (name, plugin dir, pattern)
PLUGINS = [
    ("acpi-phat", None, "acpi-phat"), ("amd-afc", None, "amd-afc-state"), ("bcm57xx", None, None),
    ("ccgx", None, None), ("ccgx-dmc", None, None), ("cros-ec", None, None),
    ("ebitdo", None, None), ("elanfp", None, None), ("elantp", None, None),
    ("genesys-scaler", "genesys", "genesys-scaler-firmware"),
    ("genesys-usbhub", "genesys", "genesys-usbhub-firmware"),
    ("hughski-colorhug", None, "hughski-colorhug-device"), ("pixart-rf", None, None),
    ("realtek-alc408x", None, None), ("redfish-smbios", "redfish", "redfish-smbios"),
    ("synaptics-prometheus", None, None),
    ("synaptics-cape", None, "synaptics-cape-hid-firmware"), ("synaptics-mst", None, None),
    ("synaptics-rmi", None, None), ("uf2", None, None), ("wacom-usb", None, None),
]


def sh(argv, **kw):
    subprocess.run(argv, check=True, **kw)


def pkg(flag, libs):
    return shlex.split(subprocess.check_output(["pkg-config", flag] + libs, text=True))


def camel(name):
    return "".join(p[:1].upper() + p[1:] for p in name.replace("_", "-").split("-"))


def grep_meson(rel):
    srcs = []
    with open(os.path.join(SRC, rel, "meson.build")) as f:
        for line in f:
            if "fuzzing" not in line:
                continue
            line = line.split("#")[0]
            if "=" in line:
                line = line.split("=")[1]
            for ch in "', \n":
                line = line.replace(ch, "")
            if line:
                srcs.append(os.path.join(rel, line))
    return srcs


class Flavour:
    def __init__(self, kind):
        self.kind = kind
        self.dir = os.path.join(BUILD, kind)
        self.obj = os.path.join(self.dir, "obj")
        self.gen = os.path.join(self.dir, "gen")
        os.makedirs(self.obj, exist_ok=True)
        os.makedirs(self.gen, exist_ok=True)
        os.makedirs(os.path.join(self.gen, "libfwupd"), exist_ok=True)
        cc = os.environ.get("CC", "clang")
        if kind == "fuzz":
            san = shlex.split(os.environ["SANITIZER_FLAGS"])
            dbg = shlex.split(os.environ["DEBUG_FLAGS"])
            cov = ["-fsanitize=fuzzer-no-link"] if os.environ.get("LIB_FUZZING_ENGINE") else []
            self.cflags = ["-O1"] + san + dbg + cov
            self.ldflags = san + dbg
        else:
            self.cflags = ["-O2"] + shlex.split(os.environ.get("COVERAGE_FLAGS", ""))
            self.ldflags = shlex.split(os.environ.get("COVERAGE_FLAGS", ""))
        self.cc = cc
        self.cflags += [
            "-Wno-deprecated-declarations", "-Wno-everything", "-fPIC",
            f"-I{self.gen}", f"-I{self.gen}/libfwupd",
            f"-I{SRC}", f"-I{SRC}/rust/fwupd-ffi", f"-I{SRC}/libfwupd", f"-I{SRC}/libfwupdplugin",
        ] + pkg("--cflags", ["glib-2.0", "gio-2.0", "gmodule-2.0", "gobject-2.0", "xmlb", "libusb-1.0"])
        self.libs = pkg("--libs", ["xmlb", "libusb-1.0", "gio-2.0", "gmodule-2.0", "gobject-2.0", "glib-2.0"]) + [
            "-lpthread", "-ldl", "-lffi", "-lz", "-llzma", "-lzstd", "-lm"]
        self.write_headers()

    def write_headers(self):
        with open(os.path.join(self.gen, "libfwupd", "fwupd-version.h"), "w") as f:
            f.write("#define FWUPD_MAJOR_VERSION 0\n#define FWUPD_MINOR_VERSION 0\n#define FWUPD_MICRO_VERSION 0\n")
        defs = {
            "FWUPD_DATADIR": "/tmp", "FWUPD_DATADIR_VENDOR_IDS": "/tmp", "FWUPD_LOCALSTATEDIR": "/tmp",
            "FWUPD_LIBDIR_PKG": "/tmp", "FWUPD_SYSCONFDIR": "/tmp", "FWUPD_LIBEXECDIR": "/tmp",
            "PACKAGE_NAME": "fwupd", "PACKAGE_VERSION": "0.0.0",
        }
        with open(os.path.join(self.gen, "config.h"), "w") as f:
            for k, v in defs.items():
                f.write(f'#define {k} "{v}"\n')
            for k in ["HAVE_FUZZER", "HAVE_LIBUSB_GET_PARENT", "HAVE_REALPATH"]:
                f.write(f"#define {k}\n")

    def rustgen(self, rel, include):
        base = os.path.basename(rel).replace(".rs", "")
        c = os.path.join(self.gen, f"{base}-struct.c")
        h = os.path.join(self.gen, f"{base}-struct.h")
        sh(["python3", "libfwupdplugin/rustgen.py", rel, "--outc", c, "--outh", h, "--include", include], cwd=SRC)
        return c

    def compile_cmd(self, src, out, extra=()):
        full = src if os.path.isabs(src) else os.path.join(SRC, src)
        return [self.cc] + self.cflags + list(extra) + ["-c", full, "-o", out]

    def compile_all(self, jobs):
        """jobs: list of (src, out, extra). Compiled in parallel."""
        with concurrent.futures.ThreadPoolExecutor(JOBS) as ex:
            futs = [ex.submit(sh, self.compile_cmd(s, o, e)) for s, o, e in jobs]
            for fu in futs:
                fu.result()

    def sources(self, rel, include):
        """expand a meson dir into C sources (generating rust struct sources first)"""
        out = []
        for s in grep_meson(rel):
            if s.endswith(".c"):
                out.append(s)
            elif s.endswith(".rs"):
                out.append(self.rustgen(s, include))
        return out

    def objs_for(self, srcs, tag, extra=()):
        jobs, outs = [], []
        for s in srcs:
            o = os.path.join(self.obj, tag, os.path.basename(s).replace(".c", ".o"))
            os.makedirs(os.path.dirname(o), exist_ok=True)
            jobs.append((s, o, extra))
            outs.append(o)
        self.compile_all(jobs)
        return outs

    def link(self, objs, out, extra_objs=()):
        sh([self.cc] + self.ldflags + list(objs) + list(extra_objs) + self.libs + ["-o", out])


def build_cargo(flavour):
    target = os.path.join(BUILD, "cargo")
    env = dict(os.environ)
    if flavour.kind == "fuzz":
        env["RUSTFLAGS"] = os.environ.get("RUST_DEBUG_FLAGS", "")
    sh(["cargo", "build", "--release", "--package", "fwupd-ffi", "--target-dir", target], cwd=SRC, env=env)
    lib = os.path.join(target, "release", "libfwupd_ffi.a")
    if flavour.kind != "fuzz":
        return lib
    # The prebuilt Rust std/core/alloc objects inside the staticlib carry DWARF 4; Mayhem's triage can
    # only read DWARF < 4, so drop their debug info and keep the fwupd crates' (DWARF 3) intact.
    tmp = os.path.join(BUILD, "cargo-members")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    sh(["ar", "x", lib], cwd=tmp)
    members = sorted(os.listdir(tmp))
    for m in members:
        if not m.startswith("fwupd"):
            sh(["strip", "--strip-debug", os.path.join(tmp, m)])
    out = os.path.join(BUILD, "libfwupd_ffi_dwarf3.a")
    if os.path.exists(out):
        os.unlink(out)
    sh(["ar", "rcs", out] + members, cwd=tmp)
    return out


def render(template, out, gtype, include):
    with open(os.path.join(SRC, "libfwupdplugin", template)) as f:
        blob = f.read()
    blob = blob.replace("@GTYPE@", gtype).replace("@INCLUDE@", include)
    with open(out, "w") as f:
        f.write(blob)
    return out


def main():
    os.makedirs(BUILD, exist_ok=True)
    ffi = None
    for kind in sys.argv[1:] or ["fuzz", "plain"]:
        fl = Flavour(kind)
        if ffi is None:
            ffi = build_cargo(fl)
        # the shared library objects, kept in an archive so each binary only pulls what it needs
        lib_srcs = fl.sources("libfwupd", "fwupd-build.h") + fl.sources("libfwupdplugin", "fwupd.h")
        lib_objs = fl.objs_for(lib_srcs, "lib")
        archive = os.path.join(fl.dir, "libfwupd-all.a")
        if os.path.exists(archive):
            os.unlink(archive)
        sh(["ar", "rcs", archive] + lib_objs)
        archive_libs = [archive, ffi]

        # harness entry points
        if kind == "fuzz":
            engine = shlex.split(os.environ["LIB_FUZZING_ENGINE"])
            lsan = os.path.join(fl.obj, "lsan_off.o")
            sh([fl.cc] + fl.cflags + ["-c", os.environ["LSAN_OFF_SRC"], "-o", lsan])
            sa_main = os.path.join(fl.obj, "standalone_main.o")
            sh([fl.cc] + fl.cflags + ["-c", os.environ["STANDALONE_FUZZ_MAIN"], "-o", sa_main])
        else:
            os.makedirs(os.path.join(fl.dir, "bin"), exist_ok=True)

        fuzzers = [(n, None, p or f"{n}-firmware") for n, p in CORE] + [
            (n, d or n, p or f"{n}-firmware") for n, d, p in PLUGINS]

        plugin_cache = {}
        for name, plugin_dir, pattern in fuzzers:
            gtype = "FU_TYPE_" + pattern.replace("-", "_").upper()
            include = f"plugins/{plugin_dir}/fu-{pattern}.h" if plugin_dir else f"libfwupdplugin/fu-{pattern}.h"
            plug_objs = []
            if plugin_dir:
                if plugin_dir not in plugin_cache:
                    srcs = fl.sources(f"plugins/{plugin_dir}", "fwupdplugin.h")
                    plugin_cache[plugin_dir] = fl.objs_for(
                        srcs, "plugin-" + plugin_dir, extra=[f'-DG_LOG_DOMAIN="FuPlugin{camel(name)}"'])
                plug_objs = plugin_cache[plugin_dir]
            if kind == "fuzz":
                src = render("fu-fuzzer-firmware.c.in", os.path.join(fl.gen, f"{name}_fuzzer.c"), gtype, include)
                obj = os.path.join(fl.obj, f"{name}_fuzzer.o")
                sh(fl.compile_cmd(src, obj))
                fl.link([obj] + plug_objs + [lsan] + engine, os.path.join(SRC, f"{name}_fuzzer"), archive_libs)
                fl.link([obj] + plug_objs + [lsan, sa_main], os.path.join(SRC, f"{name}_fuzzer-standalone"), archive_libs)
            else:
                src = render("fu-fuzzer-generate.c.in", os.path.join(fl.gen, f"{name}_generator.c"), gtype, include)
                obj = os.path.join(fl.obj, f"{name}_generator.o")
                sh(fl.compile_cmd(src, obj))
                fl.link([obj] + plug_objs, os.path.join(fl.dir, "bin", f"{name}_generator"), archive_libs)


if __name__ == "__main__":
    main()
