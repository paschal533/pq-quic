"""Per-connection handshake time from a quic_tap trace, independent of the stack.

For each client in the trace: t0 = first client datagram seen by the tap;
t_done = first client datagram carrying a Handshake-space long-header packet
(the client's Finished flight). Both are tap timestamps, so with a delay-only tap
the client actually finished one one-way delay earlier than t_done; the offset
is the same for every variant and cancels in comparisons.
"""
import json
import sys
from collections import defaultdict


def long_types(data: bytes) -> list[int]:
    """Packet types of the coalesced long-header packets in a datagram."""
    sys.path.insert(0, __file__.rsplit("\\", 1)[0].rsplit("/", 1)[0])
    from decode_initial import split_datagram
    return [p.ptype for p in split_datagram(data)]


def main(path: str) -> None:
    first: dict[int, float] = {}
    done: dict[int, float] = {}
    c2s_initials = defaultdict(int)
    dropped = defaultdict(int)
    for line in open(path, encoding="utf-8"):
        r = json.loads(line)
        if r["dir"] != "c2s":
            continue
        c = r.get("client", 0)
        first.setdefault(c, r["t"])
        if r.get("dropped"):
            dropped[c] += 1
        types = long_types(bytes.fromhex(r["hex"]))
        if 0 in types:
            c2s_initials[c] += 1
        if 2 in types and c not in done and not r.get("dropped"):
            done[c] = r["t"]
    for c in sorted(first):
        hs = (done[c] - first[c]) * 1000 if c in done else float("nan")
        print(json.dumps({"client": c, "handshake_ms": round(hs, 2),
                          "c2s_initial_datagrams": c2s_initials[c], "c2s_dropped": dropped[c]}))


if __name__ == "__main__":
    main(sys.argv[1])
