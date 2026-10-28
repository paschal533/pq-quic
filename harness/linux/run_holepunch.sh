#!/usr/bin/env bash
# RQ3: DCUtR hole punch over two Linux NATs, hybrid vs classical ClientHello (go-libp2p v0.51.0).
# Root only (WSL2/Linux). Builds five network namespaces and removes them on exit:
#
#   hpA 192.168.1.2 -- 192.168.1.1 hpNA 11.0.0.1 --+
#                                                  br0 (hpW, relay 11.0.0.10)
#   hpB 192.168.2.2 -- 192.168.2.1 hpNB 11.0.0.2 --+
#
# Delay (netem, egress only): D/2 on each NAT's WAN veth and on each bridge port towards a NAT, so
# relay<->peer one-way = D/2 and A<->B one-way = D. Skew: extra X = 2*SKEW ms on A->relay packets only
# (prio + u32 on the relay address). B's measured DCUtR RTT grows by X while SYNC is not delayed, so B
# fires SKEW ms late and A's first Initial reaches B's NAT before B's mapping when SKEW > D.
#
# MODEL=testplans: plain snat, no filter (test-plans hole-punch-interop router/run.sh).
# MODEL=unified:   masquerade, forward policy drop, unsolicited WAN input dropped
#                  (unified-testing hole-punch images/linux/run.sh). Needs nft_ct (modprobe).
#
# Env: HP_BIN (linux build of harness/go-pair/hp), MODEL, D (one-way ms, default 100),
#      SKEWS (ms list), PAIRS (per skew), SEED, OUT, RESUME, TAG.
# Peers run with QUIC_GO_DISABLE_GSO=true. Classical = GODEBUG=tlsmlkem=0 on both peers.
# Each trial uses fresh peer processes (fresh ports, so no conntrack state carries over).
# Resumable: a cell is skipped when its .done marker exists.
set -u
: "${HP_BIN:?linux build of harness/go-pair/hp}"
MODEL=${MODEL:-unified}; D=${D:-100}; PAIRS=${PAIRS:-100}; SEED=${SEED:-23}
SKEWS=${SKEWS:-0 50 90 110 150 300 1000}
case $MODEL in testplans|unified) ;; *) echo "MODEL must be testplans or unified"; exit 2;; esac
out=${RESUME:-${OUT:-$(cd "$(dirname "$0")/../.." && pwd)/data/bench}/holepunch${TAG:+-$TAG}-$(date -u +%Y%m%dT%H%M%SZ)}
mkdir -p "$out"
NS="hpA hpNA hpW hpNB hpB"
RELAY_IP=11.0.0.10
half=$(python3 -c "print($D/2)")

teardown() {
  [ -n "${relay_pid:-}" ] && kill "$relay_pid" 2>/dev/null
  # kill anything still running inside our namespaces (strays from a killed run), then remove them
  for n in $NS; do
    ip netns pids "$n" 2>/dev/null | xargs -r kill 2>/dev/null
    ip netns del "$n" 2>/dev/null
  done
}
trap teardown EXIT

x() { ip netns exec "$@"; }

link() {  # link NS1 IF1 NS2 IF2: create with unique names in the root namespace, then move and rename
  local a=hpv$RANDOM b=hpv$RANDOM
  ip link add "$a" type veth peer name "$b"
  ip link set "$a" netns "$1"; ip link set "$b" netns "$3"
  x "$1" ip link set "$a" name "$2"; x "$3" ip link set "$b" name "$4"
  x "$1" ip link set "$2" up; x "$3" ip link set "$4" up
}

nat_rules() {  # nat_rules NS WAN_IF LAN_IF WAN_ADDR
  local ns=$1 wan=$2 lan=$3 addr=$4
  x "$ns" sysctl -qw net.ipv4.ip_forward=1
  if [ "$MODEL" = testplans ]; then
    x "$ns" nft -f - <<EOF
table ip nat {
  chain post {
    type nat hook postrouting priority 100;
    oifname "$wan" snat to $addr
  }
}
EOF
  else
    x "$ns" nft -f - <<EOF
table ip nat {
  chain post {
    type nat hook postrouting priority 100;
    oifname "$wan" masquerade
  }
}
table ip filter {
  chain input {
    type filter hook input priority 0; policy accept;
    iifname "$wan" ct state new drop
  }
  chain forward {
    type filter hook forward priority 0; policy drop;
    iifname "$lan" accept
    ct state established,related accept
  }
}
EOF
  fi
}

setup() {
  teardown
  for n in $NS; do ip netns add "$n"; x "$n" ip link set lo up; done
  x hpW ip link add br0 type bridge; x hpW ip link set br0 up; x hpW ip addr add $RELAY_IP/24 dev br0
  for s in A B; do
    local i=1; [ $s = B ] && i=2
    link hp$s eth0 hpN$s lan0
    link hpN$s wan0 hpW w$s
    x hpW ip link set w$s master br0
    x hp$s ip addr add 192.168.$i.2/24 dev eth0; x hp$s ip route add default via 192.168.$i.1
    x hpN$s ip addr add 192.168.$i.1/24 dev lan0; x hpN$s ip addr add 11.0.0.$i/24 dev wan0
    nat_rules hpN$s wan0 lan0 11.0.0.$i
    x hpW tc qdisc add dev w$s root netem delay ${half}ms
  done
  x hpNB tc qdisc add dev wan0 root netem delay ${half}ms
  set_skew 0
  # fail fast if the topology is not wired: both peers must reach the relay through their NAT
  for s in A B; do
    x hp$s ping -c1 -W2 $RELAY_IP >/dev/null || { echo "setup check failed: hp$s cannot reach the relay"; exit 3; }
    x hpN$s nft list ruleset | grep -q "type nat hook postrouting" || { echo "setup check failed: no NAT in hpN$s"; exit 3; }
  done
}

set_skew() {  # A->relay gets D/2 + 2*SKEW, everything else from A's NAT gets D/2
  local extra; extra=$(python3 -c "print($D/2 + 2*$1)")
  x hpNA tc qdisc del dev wan0 root 2>/dev/null
  x hpNA tc qdisc add dev wan0 root handle 1: prio bands 2 priomap 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1
  x hpNA tc qdisc add dev wan0 parent 1:1 handle 10: netem delay ${extra}ms
  x hpNA tc qdisc add dev wan0 parent 1:2 handle 20: netem delay ${half}ms
  x hpNA tc filter add dev wan0 parent 1: protocol ip u32 match ip dst $RELAY_IP/32 flowid 1:1
}

start_relay() {
  x hpW env QUIC_GO_DISABLE_GSO=true "$HP_BIN" -role relay -listen /ip4/$RELAY_IP/udp/4001/quic-v1 \
    -timeout 24h > "$out/relay.log" 2>&1 &
  relay_pid=$!
  # a cold start (e.g. right after WSL was idle) can take well over 10 s
  for _ in $(seq 600); do grep -q '^relay ' "$out/relay.log" && break; sleep 0.1; done
  local rid; rid=$(awk '/^relay /{print $2; exit}' "$out/relay.log")
  [ -n "$rid" ] || { echo "relay did not print its peer ID within 60 s"; exit 3; }
  RELAY="/ip4/$RELAY_IP/udp/4001/quic-v1/p2p/$rid"
  echo "relay $RELAY" | tee -a "$out/summary.txt"
}

trial() {  # trial PAIR VARIANT LOG
  local gd=""; [ "$2" = classical ] && gd=tlsmlkem=0
  local tb; tb=$(mktemp); local ta; ta=$(mktemp)
  x hpB env QUIC_GO_DISABLE_GSO=true GODEBUG=$gd "$HP_BIN" -role listen -relay "$RELAY" -timeout 90s < /dev/null > "$tb" 2>&1 &
  local bp=$!
  for _ in $(seq 300); do grep -q '^ready ' "$tb" && break; kill -0 $bp 2>/dev/null || break; sleep 0.05; done
  local id; id=$(awk '/^ready /{print $2; exit}' "$tb")
  if [ -n "$id" ]; then
    x hpA env QUIC_GO_DISABLE_GSO=true GODEBUG=$gd "$HP_BIN" -role dial -relay "$RELAY" -peer "$id" -timeout 60s < /dev/null > "$ta" 2>&1
    sleep 0.5   # let B trace its EndHolePunch
  else
    echo "listener not ready" > "$ta"
  fi
  kill -TERM $bp 2>/dev/null; wait $bp 2>/dev/null
  { sed "s/^/T $1 $2 B /" "$tb"; sed "s/^/T $1 $2 A /" "$ta"; } >> "$3"
  rm -f "$ta" "$tb"
}

[ "$MODEL" = unified ] && { modprobe nft_ct || { echo "nft_ct not available"; exit 2; }; }
uname -r > "$out/kernel.txt"
echo "model=$MODEL D=$D pairs=$PAIRS seed=$SEED skews=$SKEWS" | tee -a "$out/summary.txt"
setup
start_relay
for s in $SKEWS; do
  cell="$out/$MODEL-d$D-skew$s"
  [ -e "$cell.done" ] && { echo "skip $MODEL skew $s (done)"; continue; }
  set_skew "$s"; : > "$cell.log"
  # seeded order of the two variants within each pair (as in bench_handshake.py)
  python3 -c "import random; r=random.Random($SEED*1000+$s)
for i in range($PAIRS): print(i, *r.sample(['hybrid','classical'], 2))" |
  while read -r pair v1 v2; do
    trial "$pair" "$v1" "$cell.log"; trial "$pair" "$v2" "$cell.log"
  done
  # a cell where no listener ever came up is a harness failure, not data: leave it unmarked
  if [ "$(grep -c ' A listener not ready' "$cell.log")" -ge "$((2*PAIRS))" ]; then
    echo "$MODEL skew $s: no listener came up in any trial; cell not marked done"; exit 3
  fi
  touch "$cell.done"
  echo "$MODEL skew $s: $(grep -c '"direct":true' "$cell.log") direct of $((2*PAIRS))" | tee -a "$out/summary.txt"
done
echo "holepunch done: $out"
