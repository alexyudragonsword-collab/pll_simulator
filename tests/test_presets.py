"""Every preset's linear-model jitter lands in its declared class."""
import pytest

from pllsim import presets

BOUNDS = {
    "cppll_19p2m_4p8g": (150, 320),
    "cppll_frac_38p4m_6g": (120, 260),
    "sspll_19p2m_4p8g": (80, 220),
    # analyze() assumes a conservative 1% post-cal DSM residual; the
    # calibrated time domain lands ~150 fs
    "sspll_frac_19p2m_4p806g": (80, 320),
    "spll_100m_8g": (120, 300),
    "adpll_100m_10g": (60, 200),
    "adpll_bb_100m_10g": (60, 260),
    "ilcm_250m_12g": (60, 200),
    "mdll_150m_2p4g": (150, 600),
}


@pytest.mark.parametrize("name", list(presets.ALL_PRESETS))
def test_preset_jitter_class(name):
    pll = presets.ALL_PRESETS[name]()
    ar = pll.analyze()
    lo, hi = BOUNDS[name]
    assert lo < ar.jitter_fs < hi, f"{name}: {ar.jitter_fs:.1f} fs not in [{lo},{hi}]"
    assert ar.f0 <= 12.1e9
