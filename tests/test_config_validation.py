"""Block-level configs validate themselves, and validation never derives state.

`guiutil._revalidate` re-runs every `__post_init__` in a config tree after a
form edit.  Until now only the six architecture configs had one, so the
widest part of every form -- OscConfig's fifteen fields, the DTC, the TDC,
the sampler, the loop filter -- passed through unchecked: a zero sampling
capacitor or a negative spot offset reached the engine and came back as a
NaN or a silent nonsense.  These are the validators, and the invariant that
keeps re-running them safe.
"""
from __future__ import annotations

import ast
import importlib
import inspect
import pkgutil

import pytest

import pllsim.arch
import pllsim.blocks
from pllsim import presets
from pllsim.arch.adpll import DLFConfig
from pllsim.arch.cppll import FracConfig
from pllsim.blocks.dtc import DTCConfig
from pllsim.blocks.lockdetect import LockDetectConfig
from pllsim.blocks.loopfilter import FilterDesign
from pllsim.blocks.oscillator import OscConfig
from pllsim.blocks.sampler import SamplerConfig
from pllsim.blocks.tdc import TDCConfig
from pllsim.guiutil import make_pll


def _osc(**kw):
    base = dict(f0=4.8e9, gain=50e6)
    base.update(kw)
    return OscConfig(**base)


@pytest.mark.parametrize("build, needle", [
    (lambda: _osc(f0=0.0), "f0"),
    (lambda: _osc(gain=0.0), "gain"),
    (lambda: _osc(pn_foffset=-1e6), "pn_foffset"),
    (lambda: _osc(pn_f1f3=-1.0), "pn_f1f3"),
    (lambda: _osc(n_bands=0), "n_bands"),
    (lambda: _osc(n_bands=4, band_step_hz=0.0), "band_step_hz"),
    (lambda: _osc(v_min=1.0, v_max=0.5), "v_min"),
    (lambda: _osc(pull_lock_range_hz=-1.0), "pull_lock_range_hz"),
    (lambda: DTCConfig(t_res=0.0), "t_res"),
    (lambda: DTCConfig(t_res=1e-12, n_bits=0), "n_bits"),
    (lambda: DTCConfig(t_res=1e-12, jitter_rms_s=-1e-15), "jitter_rms_s"),
    (lambda: DTCConfig(t_res=1e-12, gain_error_residual=1.5), "gain_error_residual"),
    (lambda: DTCConfig(t_res=1e-12, inl_sin=(1e-13, 2)), "inl_sin"),
    (lambda: TDCConfig(t_res=-1e-12), "t_res"),
    (lambda: TDCConfig(t_res=1e-12, n_bits=0), "n_bits"),
    (lambda: SamplerConfig(c_samp=0.0), "c_samp"),
    (lambda: SamplerConfig(amp_v=-0.1), "amp_v"),
    (lambda: SamplerConfig(pulse_width=0.0), "pulse_width"),
    (lambda: SamplerConfig(temp_k=0.0), "temp_k"),
    (lambda: FilterDesign(c1=0.0, r2=1e3, c2=1e-9), "c1"),
    (lambda: FilterDesign(c1=1e-10, r2=-1.0, c2=1e-9), "r2"),
    (lambda: FilterDesign(c1=1e-10, r2=1e3, c2=1e-9, r3=1e3, c3=0.0), "r3"),
    (lambda: LockDetectConfig(window_s=0.0), "window_s"),
    (lambda: LockDetectConfig(window_s=1e-10, count=0), "count"),
    (lambda: DLFConfig(alpha=0.0, rho=0.0), "alpha"),
    (lambda: DLFConfig(alpha=1e-3, rho=1e-6, iir_lambdas=(1.5,)), "iir_lambdas"),
    (lambda: FracConfig(frac=1.2), "frac"),
    (lambda: FracConfig(frac=0.1, mash_order=4), "mash_order"),
    (lambda: FracConfig(frac=0.1, bits=0), "bits"),
])
def test_block_configs_refuse_values_the_engine_cannot_use(build, needle):
    with pytest.raises(ValueError, match=needle):
        build()


def test_every_preset_still_constructs():
    for name in presets.ALL_PRESETS:
        presets.ALL_PRESETS[name]()


@pytest.mark.parametrize("path, text", [
    ("osc.pn_foffset", "-1"),
    ("filt.c1", "0"),
    ("cp.icp", "0"),
    ("osc.n_bands", "0"),
])
def test_a_form_edit_reaches_the_block_validators(path, text):
    # the phone's fref edit taught us setattr bypasses __post_init__; the
    # re-validation walk only helps where a validator exists to re-run
    with pytest.raises(ValueError):
        make_pll("cppll_19p2m_4p8g", {path: text})


def _post_inits():
    for pkg in (pllsim.arch, pllsim.blocks):
        for info in pkgutil.iter_modules(pkg.__path__):
            mod = importlib.import_module(f"{pkg.__name__}.{info.name}")
            for _, cls in inspect.getmembers(mod, inspect.isclass):
                if cls.__module__ != mod.__name__ or "__post_init__" not in cls.__dict__:
                    continue
                yield cls


def test_post_init_is_a_pure_validator_everywhere():
    """_revalidate re-runs every __post_init__ on every form edit, which is
    only safe if none of them derives state.  Pin the invariant with an AST
    walk: no `self.<x> = ...` in any config's __post_init__."""
    seen, offenders = 0, []
    for cls in _post_inits():
        seen += 1
        tree = ast.parse(_dedent(inspect.getsource(cls.__post_init__)))
        for node in ast.walk(tree):
            targets = []
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
                targets = [node.target]
            for t in targets:
                if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) \
                        and t.value.id == "self":
                    offenders.append(f"{cls.__name__}.{t.attr}")
    assert seen >= 12, f"only {seen} __post_init__ found -- walk broken?"
    assert not offenders, offenders


def _dedent(src: str) -> str:
    import textwrap
    return textwrap.dedent(src)
