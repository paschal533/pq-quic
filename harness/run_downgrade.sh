#!/usr/bin/env bash
# run_downgrade.sh NAME MODE LISTEN_CMD DIAL_CMD
# dialer -> quic_tap (logs, no impairment) -> downgrade_proxy MODE -> listener.
# The tap trace (../data/NAME.jsonl) shows every ClientHello the dialer sent and what the
# server answered, so a classical-only retry or an HRR is visible.
set -u
name=$1; mode=$2; listen_cmd=$3; dial_cmd=$4
here=$(cd "$(dirname "$0")" && pwd)
read -r lp pp tp < <(python -c "import socket;s=[socket.socket(2,2) for _ in range(3)];[x.bind(('127.0.0.1',0)) for x in s];print(*[x.getsockname()[1] for x in s])")
out="$here/../data/$name.jsonl"; log=$(mktemp); plog=$(mktemp)
eval "${listen_cmd//__LP__/$lp}" >"$log" 2>&1 &
lpid=$!
for _ in $(seq 50); do grep -q "^peer " "$log" && break; sleep 0.2; done
peer=$(grep -m1 "^peer " "$log" | awk '{print $2}' | tr -d '\r')
python "$here/tap/downgrade_proxy.py" --mode "$mode" --listen "$pp" --upstream "$lp" --seconds 14 >"$plog" 2>&1 &
ppid=$!
python "$here/tap/quic_tap.py" --listen "$tp" --upstream "$pp" --out "$out" --seconds 14 >/dev/null &
tpid=$!
sleep 0.7
d=${dial_cmd//__TP__/$tp}; d=${d//__PEER__/$peer}
dial_result=$(eval "timeout 12 $d" 2>&1 | tr -d '\r' | tail -2 | tr '\n' ' ')
wait $tpid $ppid
kill $lpid 2>/dev/null; wait $lpid 2>/dev/null
echo "=== $name ($mode)"
echo "dialer: $dial_result"
echo "listener: $(grep -vE '^peer ' "$log" | tr -d '\r' | tail -2 | tr '\n' ' ')"
echo "proxy: $(tr -d '\r' <"$plog" | tail -2 | tr '\n' ' ')"
python "$here/tap/decode_initial.py" "$out" | python "$here/tap/summarise.py"
rm -f "$log" "$plog"
