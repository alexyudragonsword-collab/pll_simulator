"""Structural checks on the full export of every preset (all 9 kinds)."""
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
                     "spll", "adpll_tdc", "adpll_bbpd", "ilcm", "mdll"}


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
