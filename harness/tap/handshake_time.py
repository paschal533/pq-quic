"""Per-connection handshake time from a quic_tap trace, independent of the stack.

For each client in the trace: t0 = first client datagram seen by the tap;
t_done = first client datagram carrying a Handshake-space long-header packet
(the client's first Handshake-space packet; often only an ACK sent before the
server's whole flight has arrived, so it misses server-flight loss);
t_complete = first client datagram carrying a 1-RTT (short-header) packet, as
seen by the tap before any drop decision. The client can only send one once its
handshake is complete, so this is the client's completion time; counting only
delivered ones would add the loss of later 1-RTT packets. Both are tap timestamps, so with a delay-only tap
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


def has_short_header(data: bytes) -> bool:
    """True if a 1-RTT packet follows the coalesced long-header packets.
    A short header has the form bit clear and the fixed bit set (0b01xxxxxx);
    trailing zero padding does not match."""
    sys.path.insert(0, __file__.rsplit("\\", 1)[0].rsplit("/", 1)[0])
    from decode_initial import split_datagram
    pos = sum(len(p.raw) for p in split_datagram(data))
    return pos < len(data) and (data[pos] & 0xC0) == 0x40


def main(path: str) -> None:
    first: dict[int, float] = {}
    done: dict[int, float] = {}
    complete: dict[int, float] = {}
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
        if c not in complete and has_short_header(bytes.fromhex(r["hex"])):
            complete[c] = r["t"]
    for c in sorted(first):
        hs = (done[c] - first[c]) * 1000 if c in done else float("nan")
        cm = (complete[c] - first[c]) * 1000 if c in complete else float("nan")
        print(json.dumps({"client": c, "handshake_ms": round(hs, 2), "complete_ms": round(cm, 2),
                          "c2s_initial_datagrams": c2s_initials[c], "c2s_dropped": dropped[c]}))


if __name__ == "__main__":
    main(sys.argv[1])
