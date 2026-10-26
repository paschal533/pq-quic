#!/usr/bin/env bash
# Random-loss runs: independent per-datagram loss in both directions, 200 pairs per cell. Serial only.
set -u
cd "$(dirname "$0")"
stamp=$(date -u +%Y%m%dT%H%M%SZ)
outdir=../data/bench/randomloss-$stamp
mkdir -p "$outdir"
for stack in rust go; do
  for loss in 0.02 0.05 0.10; do
    python bench_handshake.py --stack $stack --pairs 200 --delay-ms 25 --loss $loss --seed 23 \
      --out "$outdir/$stack-loss$loss.csv" | tee -a "$outdir/summary.txt"
  done
done
echo "randomloss done: $outdir"
