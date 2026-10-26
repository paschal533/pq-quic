"""Paired handshake-latency benchmark: hybrid (X25519MLKEM768) vs classical (X25519).

One default listener and one impaired tap per run. Each pair runs one hybrid and
one classical dial in random order, back to back, so machine drift is common to
both. Every dial is a fresh process and a fresh connection; the dialer times
only its own Connect/dial call.

  python bench_handshake.py --stack go --pairs 30 --delay-ms 25 --loss 0 --out ../data/bench/x.csv
"""

import argparse
import csv
import json
import os
import random
import re
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
GO = str(HERE / "go-pair" / "gopair.exe")
RS = str(HERE / "rust-pair" / "target" / "release" / "rust-pair.exe")

STACKS = {
    "go": {
        "listen": lambda lp: [GO, "-mode", "listen", "-listen-port", str(lp), "-seconds", "3600"],
        "dial": lambda tp, peer: [GO, "-mode", "dial", "-dial-port", str(tp), "-peer", peer],
        "classical_env": {"GODEBUG": "tlsmlkem=0"},
    },
    "rust": {
        "listen": lambda lp: [RS, "listen", str(lp), "3600"],
        "dial": lambda tp, peer: [RS, "dial", str(tp), peer],
        "classical_env": {"PQQUIC_CLASSICAL": "1"},
    },
}


def drain(stream, sink: list[str]) -> None:
    """Keep reading the listener's output. If nobody reads it, the pipe fills
    (4 KiB on Windows, about 66 'accepted' lines) and the listener blocks on its
    next print and stops accepting connections."""
    for line in stream:
        sink.append(line)


def start_listener(cmd: list[str]) -> tuple[subprocess.Popen, str, list[str]]:
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        line = proc.stdout.readline()
        if line.startswith("peer "):
            log: list[str] = []
            threading.Thread(target=drain, args=(proc.stdout, log), daemon=True).start()
            return proc, line.split()[1].strip(), log
    proc.kill()
    raise RuntimeError("listener did not print its peer id")


def dial_once(cmd: list[str], extra_env: dict[str, str]) -> float | None:
    env = {**os.environ, **extra_env}
    try:
        out = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=20).stdout
    except subprocess.TimeoutExpired:
        return None
    m = re.search(r"elapsed_ms ([0-9.]+)", out)
    return float(m.group(1)) if m else None


def add_trace_times(rows: list[dict], trace: str) -> None:
    """Attach the tap-measured handshake time. Client 0 is the warm-up dial, so
    row i is client i + 1 (dials are strictly sequential)."""
    out = subprocess.run([sys.executable, str(HERE / "tap" / "handshake_time.py"), trace],
                         capture_output=True, text=True).stdout
    by_client = {d["client"]: d for d in map(json.loads, out.splitlines())}
    keys = Path(trace).with_suffix(".keys")
    if keys.exists():  # Handshake-space decryption: the client's Finished time
        hs = subprocess.run([sys.executable, str(HERE / "tap" / "handshake_space.py"), trace, str(keys)],
                            capture_output=True, text=True).stdout
        for d in map(json.loads, hs.splitlines()):
            by_client.setdefault(d["client"], {})["finished_ms"] = d.get("finished_ms")
    for i, r in enumerate(rows):
        d = by_client.get(i + 1, {})
        r["trace_hs_ms"] = d.get("handshake_ms")
        r["trace_complete_ms"] = d.get("complete_ms")
        r["trace_finished_ms"] = d.get("finished_ms")
        r["c2s_dropped"] = d.get("c2s_dropped")


def trace_medians(rows: list[dict]) -> str:
    parts = []
    for v in ("hybrid", "classical"):
        xs = sorted(r["trace_hs_ms"] for r in rows
                    if r["variant"] == v and isinstance(r.get("trace_hs_ms"), float) and r["trace_hs_ms"] == r["trace_hs_ms"])
        parts.append(f"trace_{v}_median_ms={statistics.median(xs):.1f} (n={len(xs)}, p10={xs[len(xs)//10]:.1f}, p90={xs[(9*len(xs))//10]:.1f})" if xs else f"trace_{v}=none")
    return ", ".join(parts)


def summarise(rows: list[dict]) -> dict:
    by_pair: dict[int, dict] = {}
    for r in rows:
        by_pair.setdefault(r["pair"], {})[r["variant"]] = r["elapsed_ms"]
    complete = [p for p in by_pair.values() if p.get("hybrid") is not None and p.get("classical") is not None]
    hyb = [p["hybrid"] for p in complete]
    cls = [p["classical"] for p in complete]
    ratios = sorted(p["hybrid"] / p["classical"] for p in complete)
    diffs = sorted(p["hybrid"] - p["classical"] for p in complete)

    def q(xs, f):
        return xs[min(len(xs) - 1, int(f * len(xs)))] if xs else float("nan")

    return {
        "pairs_complete": len(complete),
        "failed_hybrid": sum(1 for r in rows if r["variant"] == "hybrid" and r["elapsed_ms"] is None),
        "failed_classical": sum(1 for r in rows if r["variant"] == "classical" and r["elapsed_ms"] is None),
        "median_hybrid_ms": statistics.median(hyb) if hyb else float("nan"),
        "median_classical_ms": statistics.median(cls) if cls else float("nan"),
        "median_diff_ms": statistics.median(diffs) if diffs else float("nan"),
        "diff_iqr_ms": (q(diffs, 0.25), q(diffs, 0.75)),
        "median_ratio": statistics.median(ratios) if ratios else float("nan"),
        "ratio_iqr": (q(ratios, 0.25), q(ratios, 0.75)),
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--stack", choices=STACKS, required=True)
    p.add_argument("--pairs", type=int, default=30)
    p.add_argument("--delay-ms", type=float, default=0.0)
    p.add_argument("--loss", type=float, default=0.0)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--drop-c2s", default="", help="passed to the tap: 1-based c2s datagrams to drop per connection")
    p.add_argument("--keylog", action="store_true",
                   help="peers write TLS secrets to <trace>.keys (SSLKEYLOGFILE) so Handshake packets can be decrypted")
    p.add_argument("--out", required=True)
    a = p.parse_args()

    stack = STACKS[a.stack]
    lp = 49000 + random.randrange(500)
    tp = lp + 500
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    trace = str(Path(a.out).with_suffix(".jsonl"))

    if a.keylog:  # inherited by the listener and every dialer
        keys = Path(trace).with_suffix(".keys")
        keys.unlink(missing_ok=True)
        os.environ["SSLKEYLOGFILE"] = str(keys)
    listener, peer, listener_log = start_listener(stack["listen"](lp))
    tap = subprocess.Popen(
        [sys.executable, str(HERE / "tap" / "quic_tap.py"), "--listen", str(tp), "--upstream", str(lp),
         "--out", trace, "--seconds", "100000", "--delay-ms", str(a.delay_ms),
         "--loss", str(a.loss), "--seed", str(a.seed), "--drop-c2s", a.drop_c2s],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.0)

    # Warm-up: the listener's first connection is slower (pilot finding), so discard one dial.
    dial_once(stack["dial"](tp, peer), {})

    order_rng = random.Random(a.seed)
    rows = []
    try:
        for i in range(a.pairs):
            order = ["hybrid", "classical"]
            order_rng.shuffle(order)
            for variant in order:
                env = stack["classical_env"] if variant == "classical" else {}
                ms = dial_once(stack["dial"](tp, peer), env)
                rows.append({"pair": i, "variant": variant, "elapsed_ms": ms})
    finally:
        tap.terminate()
        listener.kill()

    time.sleep(0.5)
    add_trace_times(rows, trace)
    with open(a.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["pair", "variant", "elapsed_ms", "trace_hs_ms", "trace_complete_ms", "trace_finished_ms", "c2s_dropped"])
        w.writeheader()
        w.writerows(rows)

    s = summarise(rows)
    print(f"{a.stack} delay={a.delay_ms}ms one-way loss={a.loss} pairs={a.pairs}: "
          + ", ".join(f"{k}={v:.3f}" if isinstance(v, float) else
                      f"{k}=({v[0]:.3f},{v[1]:.3f})" if isinstance(v, tuple) else f"{k}={v}"
                      for k, v in s.items()))
    print(f"  drop_c2s=[{a.drop_c2s}] " + trace_medians(rows))
    accepted = sum(1 for line in listener_log if line.startswith("accepted"))
    print(f"  listener accepted={accepted} (expected {1 + 2 * a.pairs} incl. warm-up)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
