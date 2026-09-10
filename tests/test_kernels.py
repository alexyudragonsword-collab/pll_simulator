"""The compiled and the interpreted kernels are the same function.

core/jit.py compiles every per-cycle kernel with numba when it is installed
and runs the identical Python otherwise.  That is only true if nothing in a
kernel lowers differently in the two paths, and several things do (np.exp,
``**``, BLAS): the rules are in the module docstring, and this file is what
enforces them -- every preset, both paths, bit for bit.

The interpreted run happens in a subprocess with PLLSIM_JIT=0, because the
switch is read once at import.  When numba is not installed both runs are
interpreted and the test still proves the run is deterministic.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import numpy as np
import pytest

from pllsim import presets
from pllsim.core import jit

HAVE_NUMBA = importlib.util.find_spec("numba") is not None
CYCLES = 3000
SEED = 5

# every stock preset, once per reference edge and once oversampled where the
# engine supports it; the cases are what old-vs-new was measured on too
_RUNNER = textwrap.dedent("""
    import json, sys
    import numpy as np
    from pllsim import presets
    from pllsim.core import jit
    npz, js, cycles, seed = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
    out = {"backend": jit.backend()}
    arrays = {}
    for name in presets.ALL_PRESETS:
        pll = getattr(presets, name)()
        for tag, kw in (("edge", {}), ("fine", {"fine_oversample": 8})):
            if tag == "fine" and "fine_oversample" not in \\
                    type(pll).simulate.__code__.co_varnames:
                continue
            sim = pll.simulate(cycles, seed=seed, **kw)
            key = name + "/" + tag
            arrays[key + "/phase"] = sim.phase_err_out
            arrays[key + "/freq"] = sim.freq_out
            arrays[key + "/ctrl"] = np.asarray(sim.ctrl, dtype=float)
            for k, v in sim.cal_traces.items():
                arrays[key + "/" + k] = np.asarray(v, dtype=float)
            out[key] = sim.jitter_fs
    np.savez(npz, **arrays)
    json.dump(out, open(js, "w"))
""")


def _run(env_jit: str, tmp: Path) -> tuple[dict, dict]:
    env = dict(os.environ, PLLSIM_JIT=env_jit)
    npz, js = tmp / f"run_{env_jit}.npz", tmp / f"run_{env_jit}.json"
    subprocess.run([sys.executable, "-c", _RUNNER, str(npz), str(js),
                    str(CYCLES), str(SEED)], check=True, env=env, timeout=1800)
    return dict(np.load(npz)), json.load(open(js))


def test_backend_reports_what_is_installed():
    want = "numba" if HAVE_NUMBA and os.environ.get("PLLSIM_JIT", "1") != "0" else "python"
    assert jit.backend() == want
    # the compiled twin exposes the Python it was built from
    from pllsim.arch.cppll import cppll_kernel
    assert callable(jit.pure(cppll_kernel))
    assert (jit.pure(cppll_kernel) is not cppll_kernel) == (jit.backend() == "numba")


def test_jit_switch_is_honoured_in_a_fresh_process():
    code = "from pllsim.core import jit; print(jit.backend())"
    got = subprocess.run([sys.executable, "-c", code], check=True, capture_output=True,
                         text=True, env=dict(os.environ, PLLSIM_JIT="0")).stdout.strip()
    assert got == "python"


def test_every_preset_runs_bit_identical_compiled_and_interpreted(tmp_path):
    """Both paths, every preset, every record and calibration trace equal to
    the last bit; the jitter figures too.  With numba absent this degenerates
    to a determinism check, which is still worth having."""
    a_arr, a_js = _run("1", tmp_path)
    b_arr, b_js = _run("0", tmp_path)
    assert b_js["backend"] == "python"
    assert a_js["backend"] == ("numba" if HAVE_NUMBA else "python")
    assert set(a_arr) == set(b_arr) and len(a_arr) > 3 * len(presets.ALL_PRESETS)
    unequal = [k for k in a_arr if not np.array_equal(a_arr[k], b_arr[k])]
    assert unequal == [], f"records differ between the paths: {unequal[:8]}"
    for k in a_js:
        if k != "backend":
            assert a_js[k] == b_js[k], f"jitter differs for {k}"


@pytest.mark.skipif(not HAVE_NUMBA, reason="the speedup needs numba")
def test_compiled_loop_is_faster_than_interpreted(tmp_path):
    """A loose bound (3x on the whole simulate(), FFTs included) that a
    silent fall-back to the interpreter would fail; measured 2026-09 at
    10-40x on this call."""
    code = textwrap.dedent("""
        import time, sys
        from pllsim import presets
        pll = presets.cppll_frac_38p4m_6g()
        pll.simulate(500, seed=1)              # compile / warm up
        t0 = time.perf_counter(); pll.simulate(40000, seed=1)
        print(time.perf_counter() - t0)
    """)
    def run(flag):
        return float(subprocess.run([sys.executable, "-c", code], check=True,
                                    capture_output=True, text=True,
                                    env=dict(os.environ, PLLSIM_JIT=flag)).stdout)
    t_py, t_jit = run("0"), run("1")
    assert t_py > 3.0 * t_jit, f"interpreted {t_py:.2f}s vs compiled {t_jit:.2f}s"
