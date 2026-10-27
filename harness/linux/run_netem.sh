#!/usr/bin/env bash
# Random-loss cells with kernel netem on lo. Needs --cap-add NET_ADMIN.
# On lo every datagram (either direction) passes one netem qdisc once, so
# "delay 25ms loss X%" = 25 ms one-way delay and independent loss X per
# datagram in each direction: the same impairment as quic_tap.py.
# netem's loss draws are not seedable; --seed only fixes the dial order.
# Env: STACKS, LOSSES, PAIRS, SEED, OUT (mounted dir), plus PQQUIC_* passed to peers.
set -u
# RESUME=<existing run dir> continues a stopped run: cells whose CSV exists are skipped
# (the bench writes its CSV only after the cell completes).
out=${RESUME:-${OUT:-/out}/netem${TAG:+-$TAG}-$(date -u +%Y%m%dT%H%M%SZ)}
mkdir -p "$out"
uname -r | tee -a "$out/kernel.txt"
trap 'tc qdisc del dev lo root 2>/dev/null' EXIT
for stack in ${STACKS:-rust go}; do
  for loss in ${LOSSES:-0.02 0.05 0.10}; do
    [ -s "$out/$stack-loss$loss.csv" ] && { echo "skip $stack loss $loss (done)"; continue; }
    pct=$(python3 -c "print($loss*100)")
    tc qdisc replace dev lo root netem delay 25ms loss ${pct}%
    tc qdisc show dev lo | tee -a "$out/summary.txt"
    python3 bench_handshake.py --direct --stack $stack --pairs ${PAIRS:-200} --delay-ms 25 --loss $loss \
      --seed ${SEED:-23} --out "$out/$stack-loss$loss.csv" | tee -a "$out/summary.txt"
    tc qdisc del dev lo root
  done
done
python3 analyse_loss.py --metric elapsed_ms "$out"/*.csv | tee "$out/analysis.txt"
echo "netem done: $out"
