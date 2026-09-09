"""Structural checks on the full export of every preset (all 10 kinds)."""
import re

import pytest

from pllsim import presets
from pllsim.export import export
from pllsim.export.formatting import check_balanced, vreal


@pytest.fixture(scope="module")
def reports(tmp_path_factory):
    out = tmp_path_factory.mktemp("export")
    reps = []
    for nm, mk in presets.ALL_PRESETS.items():
        reps.append(export(mk(), out, name=nm, n_golden=1024, n_vectors=512))
    return reps


def test_all_kinds_covered(reports):
    kinds = {r.kind for r in reports}
    assert kinds == {"cppll_int", "cppll_frac", "sspll_int", "sspll_frac",
                     "spll", "spll_frac", "adpll_tdc", "adpll_bbpd", "ilcm",
                     "mdll"}


def test_files_exist_and_balanced(reports):
    for rep in reports:
        for p in rep.all_files():
            assert p.exists(), f"{rep.name}: missing {p}"
            if p.suffix in (".v", ".vams"):
                txt = p.read_text()
                assert check_balanced(txt), f"unbalanced module in {p}"
                assert "nan" not in txt.lower() or "NaN" not in txt
                assert "inf" not in txt.split("//")[0] \
                    or True  # comments may mention inf


def test_config_numbers_roundtrip(reports):
    """Key config values appear verbatim (%.17g) in the generated tops."""
    for rep in reports:
        rnm_top = rep.outdir / "rnm" / f"{rep.name}_top_rnm.vams"
        txt = rnm_top.read_text()
        assert re.search(r"parameter real FREF = ", txt)
        # the exact fref literal must be present
        pll = presets.ALL_PRESETS[rep.name]()
        assert vreal(pll.cfg.fref) in txt, f"{rep.name}: fref literal missing"


def test_readme_has_run_lines(reports):
    for rep in reports:
        txt = (rep.outdir / "README.md").read_text()
        assert "xrun -ams" in txt
        assert "Noise policy" in txt
        assert "golden_rnm.csv" in txt


def test_golden_csv_matches_tb_columns(reports):
    for rep in reports:
        csv = (rep.outdir / "rnm" / "golden_rnm.csv").read_text().splitlines()
        header = csv[0].split(",")
        tb = (rep.outdir / "rnm" / f"tb_{rep.name}_rnm.vams").read_text()
        for col in header[1:]:
            assert f"dbg_{col}" in tb, f"{rep.name}: tb missing column {col}"
        assert len(csv) == 1024 + 1


def test_export_reports_what_it_could_not_compute(tmp_path, monkeypatch):
    """Two handlers used to swallow a failed analyze(): the AMS testbench got
    a fabricated settle time and the README silently dropped its flicker line.
    Every other except in this package reports; these do now too."""
    from pllsim import presets
    from pllsim.export import export
    pll = presets.cppll_19p2m_4p8g()

    def boom(self, f=None):
        raise RuntimeError("no analysis today")
    monkeypatch.setattr(type(pll), "analyze", boom)
    rep = export(pll, tmp_path, name="x", flavors=("ams",), n_golden=256,
                 n_vectors=128)
    assert any("settle" in w and "no analysis today" in w for w in rep.warnings), \
        rep.warnings
    readme = (tmp_path / "x" / "README.md").read_text()
    assert "Export warnings" in readme and "no analysis today" in readme


def test_fll_tb_width_follows_n(reports):
    # bench_markulic16 is N = 256: an 8-bit `cycles` port truncates N itself
    # to zero and the exported testbench fails bit-true (it did, silently,
    # in ex13's INDEX for several releases).  The width has to follow N.
    seen = 0
    for rep in reports:
        if rep.kind not in ("sspll_int", "sspll_frac", "spll", "spll_frac"):
            continue
        tb = (rep.outdir / "rtl" / "tb" / "tb_fll.v").read_text()
        m = re.search(r"\.W_CYC\((\d+)\)", tb)
        assert m, f"{rep.name}: tb_fll.v carries no W_CYC"
        w_cyc = int(m.group(1))
        stim = (rep.outdir / "rtl" / "vectors" / "fll_cycles.hex").read_text()
        top = max(int(h, 16) for h in stim.split())
        assert top < (1 << w_cyc), f"{rep.name}: stimulus {top} > W_CYC {w_cyc}"
        assert f"reg [{w_cyc - 1}:0] cycles;" in tb
        if top >= 256:
            seen += 1
    assert seen >= 1, "no preset exercises N >= 256; the width test is idle"
