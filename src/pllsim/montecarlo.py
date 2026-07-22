"""Monte Carlo mismatch / process-corner analysis.

The user supplies a `build(rng)` function that draws one instance's
impairment parameters from the given Generator and returns

    (pll, sim_kwargs, params)

where `pll` is any architecture instance, `sim_kwargs` are passed to
simulate() (the per-run seed is injected automatically), and `params` is a
dict of the drawn values (recorded per run for correlation plots).

monte_carlo() runs N such instances (multiprocess by default), extracting
per-run metrics: integrated jitter, lock time, detected spurs, final
calibration values, plus anything a user metric function adds.

`build` must be picklable (module-level function) for n_jobs > 1;
n_jobs = 1 works with any callable.
"""
from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field

import numpy as np


def _run_one(args):
    build, seed = args
    rng = np.random.default_rng(seed)
    try:
        pll, sim_kwargs, params = build(rng)
        sim_kwargs = dict(sim_kwargs)
        sim_kwargs.setdefault("seed", int(rng.integers(0, 2**31)))
        sim = pll.simulate(**sim_kwargs)
        metrics = {
            "jitter_fs": sim.jitter_fs,
            "lock_time_us": (sim.lock_time_s or np.nan) * 1e6,
        }
        for fo, dbc in sim.spurs_fft.items():
            metrics[f"spur_{fo / 1e3:.0f}k_dbc"] = dbc
        for name, tr in sim.cal_traces.items():
            arr = np.asarray(tr, dtype=float)
            if arr.ndim == 1 and arr.size:
                metrics[f"cal_{name}_final"] = float(arr[-1])
        return metrics, params, None
    except Exception as exc:            # a diverged run is data, not a crash
        return None, None, repr(exc)


@dataclass
class MCResult:
    metrics: dict[str, np.ndarray]
    params: dict[str, np.ndarray]
    n_runs: int
    failures: list[str] = field(default_factory=list)

    @property
    def n_ok(self) -> int:
        return self.n_runs - len(self.failures)

    def yield_frac(self, metric: str, limit: float, sense: str = "<") -> float:
        """Fraction of runs meeting `metric sense limit` (NaN = fail unless
        the metric is a spur, where NaN means below the noise floor = pass
        for '<')."""
        v = self.metrics[metric]
        nan_pass = sense == "<" and metric.startswith("spur_")
        ok = np.where(np.isnan(v), nan_pass,
                      v < limit if sense == "<" else v > limit)
        return float(np.mean(ok))

    def summary(self) -> str:
        lines = [f"=== Monte Carlo: {self.n_ok}/{self.n_runs} runs ok ==="]
        for name, v in self.metrics.items():
            vv = v[~np.isnan(v)]
            if vv.size == 0:
                lines.append(f"{name:26s} all NaN")
                continue
            lines.append(
                f"{name:26s} mean {np.mean(vv):10.3f}  std {np.std(vv):9.3f}  "
                f"p5 {np.percentile(vv, 5):10.3f}  p95 {np.percentile(vv, 95):10.3f}")
        if self.failures:
            lines.append(f"failures: {self.failures[:3]}...")
        return "\n".join(lines)


def monte_carlo(build, n_runs: int, seed: int = 0,
                n_jobs: int | None = None) -> MCResult:
    seeds = np.random.SeedSequence(seed).spawn(n_runs)
    jobs = [(build, s) for s in seeds]
    if n_jobs is None:
        n_jobs = min(os.cpu_count() or 1, n_runs)
    if n_jobs > 1:
        with ProcessPoolExecutor(max_workers=n_jobs) as ex:
            results = list(ex.map(_run_one, jobs))
    else:
        results = [_run_one(j) for j in jobs]

    metric_rows = [m for m, _, _ in results if m is not None]
    param_rows = [p for _, p, _ in results if p is not None]
    failures = [e for _, _, e in results if e is not None]

    def collate(rows) -> dict[str, np.ndarray]:
        keys: list[str] = []
        for r in rows:
            for k in r:
                if k not in keys:
                    keys.append(k)
        return {k: np.array([r.get(k, np.nan) for r in rows], dtype=float)
                for k in keys}

    return MCResult(metrics=collate(metric_rows), params=collate(param_rows),
                    n_runs=n_runs, failures=failures)


def plot_mc(result: MCResult, metrics: list[str] | None = None,
            save: str | None = None):
    """Histogram grid of selected metrics."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    names = metrics or [k for k in result.metrics
                        if not k.startswith("cal_")][:6]
    n = len(names)
    ncol = min(n, 3)
    nrow = (n + ncol - 1) // ncol
    fig, axes = plt.subplots(nrow, ncol, figsize=(4.2 * ncol, 3.2 * nrow),
                             squeeze=False)
    for ax, name in zip(axes.flat, names):
        v = result.metrics[name]
        vv = v[~np.isnan(v)]
        if vv.size:
            ax.hist(vv, bins=max(10, int(np.sqrt(vv.size) * 1.5)),
                    color="C0", alpha=0.85)
            ax.axvline(np.mean(vv), color="r", ls="--", lw=1)
        n_nan = int(np.isnan(v).sum())
        ax.set_title(name + (f"  ({n_nan} NaN)" if n_nan else ""), fontsize=9)
        ax.grid(alpha=0.3)
    for ax in axes.flat[n:]:
        ax.axis("off")
    fig.suptitle(f"Monte Carlo, {result.n_ok} runs")
    fig.tight_layout()
    if save:
        fig.savefig(save, dpi=140)
    return fig
