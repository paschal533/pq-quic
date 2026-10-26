#!/usr/bin/env bash
# Targeted-loss runs: drop a specific client datagram in every connection. Serial only.
set -u
cd "$(dirname "$0")"
stamp=$(date -u +%Y%m%dT%H%M%SZ)
outdir=../data/bench/targeted-$stamp
mkdir -p "$outdir"
for stack in go rust; do
  for drop in "" "1" "2"; do
    python bench_handshake.py --stack $stack --pairs 30 --delay-ms 25 --seed 11 --drop-c2s "$drop" \
      --out "$outdir/$stack-drop${drop:-none}.csv" | tee -a "$outdir/summary.txt"
  done
done
echo "targeted done: $outdir"
