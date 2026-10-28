"""Summarise RQ3 hole-punch cell logs from linux/run_holepunch.sh against notes/prediction-rq3.md.

  python analyse_holepunch.py ../data/bench/holepunch-<stamp>/*-skew*.log

Each log line is "T <pair> <variant> <A|B> <peer stdout line>". Per trial:
  direct   A printed result with "direct": true
  attempts number of StartHolePunch events traced by B (the initiator)
  t_punch  A's EndHolePunch EllapsedTime (ms) of its successful attempt
"""

from __future__ import annotations

import json
import math
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

VARIANTS = ("hybrid", "classical")


def parse(path: Path) -> dict[tuple[int, str], dict]:
    trials: dict[tuple[int, str], dict] = defaultdict(lambda: {"direct": False, "attempts": 0, "t_punch": None})
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split(" ", 4)
        if len(parts) < 5 or parts[0] != "T":
            continue
        _, pair, variant, role, rest = parts
        t = trials[(int(pair), variant)]
        if role == "A" and rest.startswith("result "):
            t["direct"] = bool(json.loads(rest[7:]).get("direct"))
        elif rest.startswith("event "):
            ev = json.loads(rest[6:])
            if role == "B" and ev["type"] == "StartHolePunch":
                t["attempts"] += 1
            if role == "A" and ev["type"] == "EndHolePunch" and ev["evt"].get("Success"):
                t["t_punch"] = ev["evt"]["EllapsedTime"] / 1e6
    return trials


def fisher_two_sided(a: int, b: int, c: int, d: int) -> float:
    """Two-sided Fisher exact p for [[a, b], [c, d]]."""
    n1, n2, k = a + b, c + d, a + c

    def p(x: int) -> float:
        return math.comb(n1, x) * math.comb(n2, k - x) / math.comb(n1 + n2, k)

    obs = p(a)
    lo, hi = max(0, k - n2), min(k, n1)
    return min(1.0, sum(p(x) for x in range(lo, hi + 1) if p(x) <= obs * (1 + 1e-9)))


def summarise(path: Path) -> None:
    trials = parse(path)
    rows = {}
    for v in VARIANTS:
        ts = [t for (_, var), t in trials.items() if var == v]
        ok = sum(t["direct"] for t in ts)
        multi = sum(t["attempts"] > 1 for t in ts)
        tp = [t["t_punch"] for t in ts if t["t_punch"] is not None]
        rows[v] = (len(ts), ok, multi, tp)
        med = f"{statistics.median(tp):7.1f}" if tp else "    n/a"
        print(f"  {v:9} n={len(ts):3} direct={ok:3} ({100*ok/max(len(ts),1):5.1f}%) "
              f">1 attempt={multi:3} t_punch median={med} ms")
    (nh, oh, mh, th), (nc, oc, mc, tc) = rows["hybrid"], rows["classical"]
    p = fisher_two_sided(oh, nh - oh, oc, nc - oc) if nh and nc else float("nan")
    dmed = statistics.median(th) - statistics.median(tc) if th and tc else float("nan")
    print(f"  success diff {100*(oh/max(nh,1) - oc/max(nc,1)):+.1f} pp (Fisher p={p:.3f}); "
          f">1-attempt diff {100*(mh/max(nh,1) - mc/max(nc,1)):+.1f} pp; t_punch median diff {dmed:+.1f} ms")


def skew_of(path: Path) -> int:
    m = re.search(r"skew(\d+)", path.name)
    return int(m.group(1)) if m else -1


def main(paths: list[str]) -> None:
    for p in sorted((Path(x) for x in paths), key=lambda q: (q.name.split("-")[0], skew_of(q))):
        print(p.name)
        summarise(p)


if __name__ == "__main__":
    main(sys.argv[1:])
