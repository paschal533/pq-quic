#!/usr/bin/env bash
# Phase 2 cost table: netem profiles on lo, both stacks, hybrid vs classical paired per iteration.
# Run as root in WSL2/Linux (tc). One-way delays 0/25/75/150 ms = RTT 0 (LAN) / 50 / 150 / 300 ms;
# loss 0 / 1 / 5 % per datagram in each direction (on lo every datagram passes netem once).
# Peers must run with GSO off (PQQUIC_DISABLE_GSO=1, QUIC_GO_DISABLE_GSO=true): netem on lo keeps or
# drops a GSO batch as a unit (CLAIMS.md method notes).
# Resumable: RESUME=<dir> skips cells whose CSV exists (the bench writes it only when a cell completes).
# Env: STACKS, DELAYS, LOSSES, PAIRS, SEED, OUT, RESUME, TAG.
set -u
cd "$(dirname "$0")/.."
: "${PQQUIC_RS_BIN:?Linux rust-pair build}" "${PQQUIC_GO_BIN:?Linux gopair build}"
[ "${PQQUIC_DISABLE_GSO:-}" = 1 ] && [ "${QUIC_GO_DISABLE_GSO:-}" = true ] \
  || { echo "refusing to run with GSO on (set PQQUIC_DISABLE_GSO=1 QUIC_GO_DISABLE_GSO=true)"; exit 2; }
out=${RESUME:-${OUT:-$(pwd)/../data/bench}/profiles${TAG:+-$TAG}-$(date -u +%Y%m%dT%H%M%SZ)}
mkdir -p "$out"
uname -r | tee -a "$out/kernel.txt"
trap 'tc qdisc del dev lo root 2>/dev/null' EXIT
for stack in ${STACKS:-rust go}; do
  for d in ${DELAYS:-0 25 75 150}; do
    for loss in ${LOSSES:-0 0.01 0.05}; do
      csv="$out/$stack-d$d-loss$loss.csv"
      [ -s "$csv" ] && { echo "skip $stack d$d loss$loss (done)"; continue; }
      pct=$(python3 -c "print($loss*100)")
      tc qdisc replace dev lo root netem delay ${d}ms loss ${pct}%
      tc qdisc show dev lo | tee -a "$out/summary.txt"
      python3 bench_handshake.py --direct --stack "$stack" --pairs "${PAIRS:-200}" --delay-ms "$d" --loss "$loss" \
        --seed "${SEED:-23}" --out "$csv" | tee -a "$out/summary.txt"
      tc qdisc del dev lo root
    done
  done
done
echo "profiles done: $out"
