"""Recompute the trace columns of existing bench CSVs from their .jsonl traces
(after a change to tap/handshake_time.py). Rows map to clients as in the bench:
client 0 is the warm-up dial, row i is client i + 1.

  python backfill_trace.py ../data/bench/<run>/*.csv
"""
import csv
import sys
from pathlib import Path

from bench_handshake import add_trace_times

FIELDS = ["pair", "variant", "elapsed_ms", "trace_hs_ms", "trace_complete_ms", "trace_finished_ms", "c2s_dropped"]


def main(paths: list[str]) -> int:
    for path in paths:
        with open(path, encoding="utf-8") as f:
            rows = [{"pair": r["pair"], "variant": r["variant"], "elapsed_ms": r["elapsed_ms"]} for r in csv.DictReader(f)]
        add_trace_times(rows, str(Path(path).with_suffix(".jsonl")))
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(rows)
        print(f"backfilled {path} ({len(rows)} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
