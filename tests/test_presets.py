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
    # SPLL fractional: reference-referred PD puts DTC noise x N at the
    # output; analyze() carries the conservative 1% post-cal DSM residual
    "spll_frac_52m_6p253g": (120, 400),
    "adpll_100m_10g": (60, 200),
    "adpll_bb_100m_10g": (60, 260),
    "ilcm_250m_12g": (60, 200),
    "mdll_150m_2p4g": (150, 600),
    # JSSC benchmark presets: linear-model jitter vs published class
    "bench_gao09_sspll_55p25m_2p21g": (90, 180),         # published 150
    "bench_dartizio23_adpllbb_500m_9p2515g": (40, 100),  # 77 (time domain)
    "bench_markulic16_sspll_40m_10p24g": (120, 230),     # published 176
    "bench_markulic16_sspll_frac_40m_10p25g": (150, 260),  # published 198
    "bench_wu19_spll_frac_52m_6p253g": (55, 105),        # published 75
}


@pytest.mark.parametrize("name", list(presets.ALL_PRESETS))
def test_preset_jitter_class(name):
    pll = presets.ALL_PRESETS[name]()
    ar = pll.analyze()
    lo, hi = BOUNDS[name]
    assert lo < ar.jitter_fs < hi, f"{name}: {ar.jitter_fs:.1f} fs not in [{lo},{hi}]"
    assert ar.f0 <= 12.1e9
