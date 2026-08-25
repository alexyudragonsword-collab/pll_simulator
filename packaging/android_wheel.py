"""Build a Chaquopy-installable wheel with parts of pllsim compiled to native code.

Why this exists
---------------
The app ships Python.  An APK is a zip, Chaquopy's payload inside it is a zip,
and `.pyc` gives back names, line numbers and docstrings to anyone who runs
`strings` -- measured on this codebase, the whole double-sideband convention
note came out of a compiled `core/jitter` in plain text.  Compiling the
modelling modules to `.so` replaces that with machine code.

Be clear about what it does *not* buy: `assets/www/app.js` stays plain text, so
the bridge's method names, arguments and the entire UI flow remain readable,
and the preset values are one `fields()` call away at runtime.  This raises the
cost of reading the *formulas*, nothing else.

How it works
------------
Every input is public and standard, which is the reason this is only a few
hundred lines:

* Android CPython (headers + ``libpython3.10.so``) is published on **Maven
  Central**, not behind chaquo.com -- ``com.chaquo.python:target``.
* The compiler is the plain NDK clang; Chaquopy's own ``target/android-env.sh``
  does nothing more exotic.
* The wheel tag format is read from Chaquopy's ``server/pypi/build-wheel.py``:
  ``cp310-cp310-android_21_arm64_v8a``.
* Cythonised pure-Python modules need **only** ``Python.h`` -- verified by
  compiling one with no numpy include path.  numpy/scipy/matplotlib stay as
  Chaquopy's prebuilt wheels; nothing here rebuilds them.

On 3.10 the generated C stays on the public API: Cython's
``internal/pycore_frame.h`` include sits behind ``PY_VERSION_HEX >= 0x030b00a6``,
so the patch version of the headers is not load-bearing.  On 3.11+ it would be,
and this script would need the exact target build.

Usage
-----
    python packaging/android_wheel.py --abi arm64-v8a --ndk $ANDROID_NDK_HOME
    python packaging/android_wheel.py --host          # host build, for testing

``--host`` compiles for the machine it runs on with the ordinary compiler.  It
exists so the assembly logic is exercised without an NDK -- the cross build then
differs only in which compiler and headers are used.
"""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import os
import shutil
import subprocess
import sys
import sysconfig
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "pllsim"

#: Compiled to native code: the modelling packages, 31 modules of the 85.
#:
#: This is exactly the set the full suite was run against with every `.py`
#: deleted -- 564 passed, 13 skipped, analyze() unchanged at 258.3043 fs -- so
#: the boundary is a measured one rather than a guess about what matters.
#:
#: `presets.py` is deliberately NOT here, and the reason is worth keeping:
#: compiling it does not hide the calibration values.  They end up as IEEE-754
#: doubles in the constant pool, where a four-line script finds each one
#: exactly (-122, 4.8e9 and 1.92e7 each matched once in a test build), and the
#: preset function names stay in the symbol table.  They are also one
#: `fields()` call away at runtime regardless.  Compiling it would be build
#: surface bought for the appearance of protection.
COMPILE_PACKAGES = ["core", "arch", "blocks", "calibration"]

#: Chaquopy 15.0.1 resolves `version = "3.10"` to this target build -- read
#: from Common.java at tag 15.0.1.  Bump both together.
TARGET_VERSION = "3.10.13-0"
PY_TAG = "cp310"
API_LEVEL = 21

MAVEN = ("https://repo.maven.apache.org/maven2/com/chaquo/python/target/"
         "{v}/target-{v}-{abi}.zip")

#: ABI -> the clang target triplet the NDK names its wrappers with.
TRIPLETS = {
    "arm64-v8a": "aarch64-linux-android",
    "x86_64": "x86_64-linux-android",
    "armeabi-v7a": "armv7a-linux-androideabi",
    "x86": "i686-linux-android",
}


def run(cmd: list[str], **kw) -> None:
    print("  $", " ".join(str(c) for c in cmd[:6]),
          "…" if len(cmd) > 6 else "", flush=True)
    subprocess.run(cmd, check=True, **kw)


def fetch_target(abi: str, work: Path) -> tuple[Path, Path]:
    """Android CPython headers and libpython, straight from Maven Central."""
    url = MAVEN.format(v=TARGET_VERSION, abi=abi)
    zip_path = work / f"target-{abi}.zip"
    if not zip_path.exists():
        print(f"  fetching {url}", flush=True)
        urllib.request.urlretrieve(url, zip_path)
    dest = work / f"target-{abi}"
    if not dest.exists():
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(dest)
    include = dest / "include" / f"python{PY_TAG[2]}.{PY_TAG[3:]}"
    libdir = dest / "jniLibs" / abi
    if not include.is_dir():
        raise SystemExit(f"no headers in {dest}; layout changed?")
    if not libdir.is_dir():
        raise SystemExit(f"no jniLibs/{abi} in {dest}; wrong ABI name?")
    return include, libdir


def cythonize(tree: Path) -> list[Path]:
    """Translate the chosen packages to C, in place.

    ``--no-docstrings`` is not cosmetic.  Cython keeps docstrings by default,
    and they are the single most readable thing left in a compiled module:
    without this flag `strings` on the result still prints the PSD convention
    note verbatim.  Verified both ways.
    """
    sources: list[Path] = []
    for pkg in COMPILE_PACKAGES:
        for py in sorted((tree / pkg).glob("*.py")):
            sources.append(py)
    if not sources:
        raise SystemExit(f"nothing to compile under {tree}")
    for py in sources:
        # module name must be the dotted path, or the generated init function
        # is named for the bare file and the import fails at runtime
        rel = py.relative_to(tree.parent).with_suffix("")
        modname = ".".join(rel.parts)
        run([sys.executable, "-m", "cython", "-3", "--no-docstrings",
             "--module-name", modname, "-o", str(py.with_suffix(".c")), str(py)])
    return [p.with_suffix(".c") for p in sources]


def compile_c(csrc: Path, include_dirs: list[Path], cc: str,
              extra: list[str], libdir: Path | None) -> Path:
    so = csrc.with_suffix(".so")
    cmd = [cc, "-shared", "-fPIC", "-O2", "-fvisibility=hidden"]
    for inc in include_dirs:
        cmd += ["-I", str(inc)]
    cmd += extra + ["-o", str(so), str(csrc)]
    if libdir is not None:
        cmd += ["-L", str(libdir), f"-lpython{PY_TAG[2]}.{PY_TAG[3:]}"]
    run(cmd)
    return so


def build_tree(work: Path) -> Path:
    """A copy of the package to mutate, so the source tree is never touched."""
    tree = work / "pllsim"
    if tree.exists():
        shutil.rmtree(tree)
    shutil.copytree(SRC, tree, ignore=shutil.ignore_patterns("__pycache__"))
    return tree


def wheel_metadata(work: Path) -> Path:
    """Reuse the real dist-info rather than hand-writing METADATA.

    Dependencies, requires-python and the description all live in
    pyproject.toml; regenerating them here would be a second copy that drifts.
    """
    out = work / "refwheel"
    if not out.exists():
        out.mkdir()
        run([sys.executable, "-m", "build", "--wheel", "--outdir", str(out),
             str(ROOT)])
    whl = next(out.glob("pllsim-*.whl"))
    extracted = work / "refwheel-x"
    if not extracted.exists():
        with zipfile.ZipFile(whl) as z:
            z.extractall(extracted)
    return next(extracted.glob("pllsim-*.dist-info"))


def assemble(tree: Path, dist_info: Path, tag: str, outdir: Path) -> Path:
    """Zip the package plus a retagged dist-info into a wheel.

    Hand-assembled rather than driven through setuptools: the tree already
    contains exactly what should ship, and `package-data` would have to be
    taught about `.so` files that only exist during this build.
    """
    # strip ".dist-info" first: splitting the raw directory name on "-" makes
    # the version "0.9.2.dist", and pip rejects a wheel whose filename does
    # not parse
    version = dist_info.name[: -len(".dist-info")].split("-")[1]
    name = f"pllsim-{version}-{tag}.whl"
    outdir.mkdir(parents=True, exist_ok=True)
    out = outdir / name
    records: list[tuple[str, str, int]] = []

    def add(z: zipfile.ZipFile, arc: str, data: bytes) -> None:
        z.writestr(arc, data)
        digest = base64.urlsafe_b64encode(
            hashlib.sha256(data).digest()).rstrip(b"=").decode()
        records.append((arc, f"sha256={digest}", len(data)))

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(tree.rglob("*")):
            if path.is_dir() or path.suffix in {".c", ".pyc"}:
                continue
            arc = str(Path("pllsim") / path.relative_to(tree))
            add(z, arc, path.read_bytes())
        # rglob, not iterdir: modern setuptools puts the licence under a
        # `licenses/` subdirectory, and treating that directory as a file
        # aborted the build
        for path in sorted(dist_info.rglob("*")):
            if path.is_dir() or path.name == "RECORD":
                continue
            data = path.read_bytes()
            if path.name == "WHEEL":
                # the tag is the whole point: pip picks a wheel by it, and a
                # py3-none-any tag would let it install on the wrong ABI
                lines = [ln for ln in data.decode().splitlines()
                         if not ln.startswith(("Tag:", "Root-Is-Purelib:"))]
                lines += ["Root-Is-Purelib: false", f"Tag: {tag}"]
                data = ("\n".join(lines) + "\n").encode()
            arc = str(Path(dist_info.name) / path.relative_to(dist_info))
            add(z, arc, data)
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        for row in records:
            w.writerow(row)
        w.writerow([f"{dist_info.name}/RECORD", "", ""])
        z.writestr(f"{dist_info.name}/RECORD", buf.getvalue())
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--abi", choices=sorted(TRIPLETS))
    ap.add_argument("--ndk", default=os.environ.get("ANDROID_NDK_HOME", ""))
    ap.add_argument("--host", action="store_true",
                    help="compile for this machine instead (exercises the "
                         "assembly logic without an NDK)")
    ap.add_argument("--work", default=str(ROOT / "build-android-wheel"))
    ap.add_argument("--outdir", default=str(ROOT / "android/app/pysrc"))
    args = ap.parse_args()
    if not args.host and not args.abi:
        ap.error("--abi is required unless --host is given")

    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)
    tree = build_tree(work)
    csrcs = cythonize(tree)
    print(f"cythonised {len(csrcs)} modules", flush=True)

    if args.host:
        include_dirs = [Path(sysconfig.get_paths()["include"])]
        cc, extra, libdir = os.environ.get("CC", "cc"), [], None
        plat = sysconfig.get_platform().replace("-", "_").replace(".", "_")
        # the running interpreter's tag, not PY_TAG: that constant describes
        # the *Android* target, and using it here produced a cp310 wheel on a
        # 3.11 host that pip then refused as unsupported
        host_tag = f"cp{sys.version_info.major}{sys.version_info.minor}"
        tag = f"{host_tag}-{host_tag}-{plat}"
    else:
        if not args.ndk or not Path(args.ndk).is_dir():
            raise SystemExit("--ndk must point at an NDK (or set "
                             "ANDROID_NDK_HOME)")
        include, libdir = fetch_target(args.abi, work)
        include_dirs = [include]
        toolchain = next((Path(args.ndk) / "toolchains/llvm/prebuilt").iterdir())
        cc = str(toolchain / "bin" /
                 f"{TRIPLETS[args.abi]}{API_LEVEL}-clang")
        if not Path(cc).exists():
            raise SystemExit(f"no compiler at {cc}")
        extra = []
        tag = (f"{PY_TAG}-{PY_TAG}-android_{API_LEVEL}_"
               f"{args.abi.replace('-', '_')}")

    for csrc in csrcs:
        compile_c(csrc, include_dirs, cc, extra, libdir)
    # the .py must go, or Python would import it in preference on some paths
    # and the whole exercise would silently do nothing
    for csrc in csrcs:
        csrc.with_suffix(".py").unlink()
        csrc.unlink()

    whl = assemble(tree, wheel_metadata(work), tag, Path(args.outdir))
    size = whl.stat().st_size / 1024
    print(f"\n{whl}  ({size:.0f} KiB, tag {tag})")
    with zipfile.ZipFile(whl) as z:
        sos = [n for n in z.namelist() if n.endswith(".so")]
        pys = [n for n in z.namelist()
               if n.endswith(".py")
               and any(f"/{pkg}/" in n for pkg in COMPILE_PACKAGES)]
    print(f"  {len(sos)} compiled modules, {len(pys)} .py left in "
          f"{'/'.join(COMPILE_PACKAGES)}")
    if pys:
        raise SystemExit("a .py survived in a compiled package -- it would "
                         "shadow the .so and this would protect nothing")
    return 0


if __name__ == "__main__":
    sys.exit(main())
