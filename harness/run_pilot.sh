#!/usr/bin/env bash
# Phase 2 pilot: serial runs only (never run two benchmarks at once).
set -u
cd "$(dirname "$0")"
stamp=$(date -u +%Y%m%dT%H%M%SZ)
outdir=../data/bench/pilot-$stamp
mkdir -p "$outdir"
for stack in go rust; do
  for profile in "0 0" "25 0" "75 0" "25 0.01" "25 0.05"; do
    set -- $profile
    python bench_handshake.py --stack $stack --pairs 30 --delay-ms $1 --loss $2 --seed 7 \
      --out "$outdir/$stack-d$1-l$2.csv" | tee -a "$outdir/summary.txt"
  done
done
echo "pilot done: $outdir"
