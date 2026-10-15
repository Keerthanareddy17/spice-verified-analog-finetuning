"""Parallel batch simulation."""
from __future__ import annotations

import multiprocessing as mp
import os
import time
from dataclasses import dataclass

from .design import Design
from .models import TEMP_NOM
from .simulator import SimResult, simulate


@dataclass
class BatchStats:
    n: int
    seconds: float
    cache_hits: int
    workers: int

    @property
    def sims_per_s(self) -> float:
        return self.n / self.seconds if self.seconds else float("inf")

    def __str__(self) -> str:
        return (f"{self.n} sims in {self.seconds:.2f}s = {self.sims_per_s:.1f} sims/s "
                f"({self.cache_hits} cache hits, {self.workers} workers)")


def _work(args: tuple) -> SimResult:
    design, temp_c, vdd_scale, use_cache = args
    return simulate(design, temp_c=temp_c, vdd_scale=vdd_scale, use_cache=use_cache)


def simulate_batch_with_stats(designs: list[Design], workers: int | None = None,
                              temp_c: float = TEMP_NOM, vdd_scale: float = 1.0,
                              use_cache: bool = True) -> tuple[list[SimResult], BatchStats]:
    """Simulate many designs in parallel (order preserved); returns results and throughput."""
    workers = workers or max(1, (os.cpu_count() or 2) - 1)
    jobs = [(d, temp_c, vdd_scale, use_cache) for d in designs]
    t0 = time.time()
    if workers == 1 or len(jobs) < 2:
        results = [_work(j) for j in jobs]
    else:
        with mp.get_context("spawn").Pool(workers) as pool:
            results = pool.map(_work, jobs, chunksize=max(1, len(jobs) // (workers * 8)))
    stats = BatchStats(len(jobs), time.time() - t0, sum(r.cached for r in results), workers)
    return results, stats


def simulate_batch(designs: list[Design], workers: int | None = None, **kw) -> list[SimResult]:
    """Like simulate_batch_with_stats but returns only the results."""
    return simulate_batch_with_stats(designs, workers, **kw)[0]
