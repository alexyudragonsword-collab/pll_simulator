"""pllsim — system-level / behavioral PLL simulation.

Architectures: CPPLL (int/frac-N), SSPLL, SPLL, ADPLL (TDC / DTC+BBPD), ILCM.
Each provides analyze() (linear phase-domain noise/stability/spur model) and
simulate() (reference-edge-driven behavioral time domain with calibration).
"""
from . import presets
from .arch.adpll import ADPLL, ADPLLConfig, DLFConfig
from .arch.cppll import CPPLL, CPPLLConfig, FracConfig
from .arch.ilcm import ILCM, ILCMConfig
from .arch.mdll import MDLL, MDLLConfig
from .arch.spll import SPLL, SPLLConfig
from .arch.sspll import SSPLL, SSPLLConfig
from .blocks.chargepump import CPConfig
from .blocks.dtc import DTCConfig
from .blocks.loopfilter import FilterDesign
from .blocks.oscillator import OscConfig
from .blocks.sampler import SamplerConfig
from .blocks.tdc import TDCConfig

try:                                    # single source: the installed dist
    from importlib.metadata import version as _v
    __version__ = _v("pllsim")
except Exception:                       # running from a source tree, not installed
    __version__ = "0+unknown"

__all__ = [
    "ADPLL", "ADPLLConfig", "DLFConfig",
    "CPPLL", "CPPLLConfig", "FracConfig",
    "ILCM", "ILCMConfig",
    "MDLL", "MDLLConfig",
    "SPLL", "SPLLConfig",
    "SSPLL", "SSPLLConfig",
    "CPConfig", "DTCConfig", "FilterDesign", "OscConfig", "SamplerConfig",
    "TDCConfig", "presets",
]
