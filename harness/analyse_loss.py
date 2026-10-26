"""Summarise random-loss benchmark CSVs: means and tails, not only medians.

Under small random loss most handshakes lose nothing, so medians hide the effect.
What matters is the mean penalty and the tail (how often a handshake stalls).

  python analyse_loss.py ../data/bench/randomloss-<stamp>/*.csv
"""

import csv
import random
import statistics
import sys
from pathlib import Path

STALL_MS = 500.0      # a handshake slower than this has waited for a pre-sample probe timeout (quinn)
BOOTSTRAP_ROUNDS = 2000


def load(path: str) -> dict[int, dict[str, float | None]]:
    pairs: dict[int, dict[str, float | None]] = {}
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            v = r["trace_hs_ms"]
            pairs.setdefault(int(r["pair"]), {})[r["variant"]] = float(v) if v not in ("", "None", "nan") else None
    return pairs


def pct(xs: list[float], q: float) -> float:
    return xs[min(len(xs) - 1, int(q * len(xs)))]


def describe(xs: list[float]) -> str:
    xs = sorted(xs)
    stall = sum(x > STALL_MS for x in xs) / len(xs)
    return (f"n={len(xs)} mean={statistics.fmean(xs):.1f} median={statistics.median(xs):.1f} "
            f"p90={pct(xs, 0.9):.1f} p99={pct(xs, 0.99):.1f} stall>{STALL_MS:.0f}ms={stall:.1%}")


def paired_mean_diff_ci(diffs: list[float], seed: int = 1) -> tuple[float, float, float]:
    rng = random.Random(seed)
    means = sorted(statistics.fmean(rng.choices(diffs, k=len(diffs))) for _ in range(BOOTSTRAP_ROUNDS))
    return statistics.fmean(diffs), pct(means, 0.025), pct(means, 0.975)


def main(paths: list[str]) -> int:
    for path in paths:
        pairs = load(path)
        print(Path(path).stem)
        for v in ("hybrid", "classical"):
            xs = [p[v] for p in pairs.values() if p.get(v) is not None]
            missing = sum(1 for p in pairs.values() if p.get(v) is None)
            print(f"  {v:9s} {describe(xs)} missing={missing}")
        diffs = [p["hybrid"] - p["classical"] for p in pairs.values()
                 if p.get("hybrid") is not None and p.get("classical") is not None]
        m, lo, hi = paired_mean_diff_ci(diffs)
        print(f"  paired mean(hybrid - classical) = {m:+.1f} ms, 95% bootstrap CI [{lo:+.1f}, {hi:+.1f}] over {len(diffs)} pairs")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
