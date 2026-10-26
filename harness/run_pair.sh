#!/usr/bin/env bash
# run_pair.sh NAME LISTEN_CMD DIAL_CMD
# LISTEN_CMD binds __LP__ and prints "peer <id>"; DIAL_CMD dials __TP__ (the tap)
# and may use __PEER__. The trace lands in ../data/NAME.jsonl and is decoded.
set -u
name=$1; listen_cmd=$2; dial_cmd=$3
here=$(cd "$(dirname "$0")" && pwd)
lp=$(( 48000 + RANDOM % 1000 )); tp=$(( lp + 1000 ))
out="$here/../data/$name.jsonl"; log=$(mktemp)
eval "${listen_cmd//__LP__/$lp}" >"$log" 2>&1 &
lpid=$!
for _ in $(seq 50); do grep -q "^peer " "$log" && break; sleep 0.2; done
peer=$(grep -m1 "^peer " "$log" | awk '{print $2}' | tr -d '\r')
python "$here/tap/quic_tap.py" --listen "$tp" --upstream "$lp" --out "$out" --seconds 6 >/dev/null &
tpid=$!
sleep 0.7
d=${dial_cmd//__TP__/$tp}; d=${d//__PEER__/$peer}
dial_result=$(eval "timeout 15 $d" 2>&1 | tr -d '\r' | tail -1)
wait $tpid
kill $lpid 2>/dev/null; wait $lpid 2>/dev/null
echo "=== $name"
echo "dialer: $dial_result"
echo "listener: $(grep -vE '^peer ' "$log" | tr -d '\r' | tail -1)"
python "$here/tap/decode_initial.py" "$out" | python "$here/tap/summarise.py"
rm -f "$log"
