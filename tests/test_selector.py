"""Architecture selector: ranking, feasibility gates, report format."""
from pllsim.selector import Requirement, select


def test_integer_channel_ranking():
    rep = select(Requirement(fref=100e6, fout=8e9, jitter_fs_max=120))
    assert rep.best is not None
    assert rep.best.jitter_fs <= 120
    by = {c.arch: c for c in rep.candidates}
    assert not by["ilcm"].feasible          # N = 80 beyond lock range
    assert not by["mdll"].feasible          # ring class above 4 GHz
    assert not by["adpll_bbpd"].feasible    # fractional-only architecture
    assert len(rep.candidates) == 7
    assert "excl." in rep.table()


def test_fractional_channel_gates():
    rep = select(Requirement(fref=52e6, fout=(120 + 0.2503) * 52e6,
                             jitter_fs_max=200, int_band=(10e3, 10e6)))
    by = {c.arch: c for c in rep.candidates}
    assert not by["ilcm"].feasible and not by["mdll"].feasible
    assert by["adpll_bbpd"].feasible        # fractional unlocks the BB loop
    assert rep.best is not None
    # the winner carries a live, analyzable instance
    ar = rep.best.pll.analyze()
    assert abs(ar.jitter_fs - rep.best.jitter_fs) < 1e-6


def test_modulation_flag_annotates():
    rep = select(Requirement(fref=250e6, fout=3e9, jitter_fs_max=200,
                             modulation=True))
    by = {c.arch: c for c in rep.candidates}
    assert any("two-point" in n for n in by["cppll"].notes)
    assert not any("two-point" in n for n in by["adpll_tdc"].notes)
