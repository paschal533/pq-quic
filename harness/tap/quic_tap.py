"""UDP relay that logs every datagram between QUIC dialers and a listener.

Dialers connect to --listen; the tap forwards to --upstream and back. Each
dialer address gets its own upstream socket, so many connections can share a
run. Optional impairment: --delay-ms adds a fixed one-way delay in each
direction (RTT grows by 2x), and --loss drops each datagram independently with
that probability (seeded by --seed). --drop-c2s 2,3 drops exactly those
1-based client-to-server datagrams of every connection (targeted loss). Each datagram is one JSON line:
{"t", "dir", "client", "len", "dropped", "hex"}. No capture driver is needed.
"""

import argparse
import heapq
import itertools
import json
import random
import selectors
import socket
import sys
import time


class Tap:
    def __init__(self, listen_port: int, upstream_port: int, delay_s: float, loss: float, seed: int,
                 drop_c2s: frozenset = frozenset()):
        self.front = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.front.bind(("127.0.0.1", listen_port))
        self.upstream = ("127.0.0.1", upstream_port)
        self.delay_s = delay_s
        self.loss = loss
        self.rng = random.Random(seed)
        self.drop_c2s = drop_c2s
        self.c2s_count: dict[tuple, int] = {}
        self.sel = selectors.DefaultSelector()
        self.sel.register(self.front, selectors.EVENT_READ, None)
        self.backs: dict[tuple, socket.socket] = {}  # client addr -> upstream socket
        self.client_ids: dict[tuple, int] = {}
        self.queue: list = []  # (due, seq, sock, data, dest)
        self.seq = itertools.count()

    def back_for(self, client: tuple) -> socket.socket:
        if client not in self.backs:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.bind(("127.0.0.1", 0))
            self.sel.register(s, selectors.EVENT_READ, client)
            self.backs[client] = s
            self.client_ids[client] = len(self.client_ids)
        return self.backs[client]

    def schedule(self, sock: socket.socket, data: bytes, dest: tuple) -> None:
        due = time.monotonic() + self.delay_s
        heapq.heappush(self.queue, (due, next(self.seq), sock, data, dest))

    def flush_due(self) -> None:
        now = time.monotonic()
        while self.queue and self.queue[0][0] <= now:
            _, _, sock, data, dest = heapq.heappop(self.queue)
            try:
                sock.sendto(data, dest)
            except OSError:
                pass  # peer gone; the trace already has the datagram

    def run(self, out_path: str, seconds: float) -> int:
        start = time.monotonic()
        count = 0
        with open(out_path, "w", encoding="utf-8") as out:
            print(f"tap ready 127.0.0.1:{self.front.getsockname()[1]} -> {self.upstream[1]}", flush=True)
            while time.monotonic() - start < seconds:
                timeout = 0.2
                if self.queue:
                    timeout = max(0.0, min(timeout, self.queue[0][0] - time.monotonic()))
                for key, _ in self.sel.select(timeout=timeout):
                    sock, client = key.fileobj, key.data
                    try:
                        data, addr = sock.recvfrom(65535)
                    except ConnectionResetError:
                        # Windows reports an ICMP port-unreachable from an earlier send
                        # as a reset on the next recv; it carries no datagram.
                        continue
                    if client is None:  # from a dialer
                        direction, client = "c2s", addr
                        dest_sock, dest = self.back_for(addr), self.upstream
                    else:  # from the listener, for `client`
                        direction, dest_sock, dest = "s2c", self.front, client
                    dropped = self.loss > 0 and self.rng.random() < self.loss
                    if direction == "c2s":
                        n = self.c2s_count[client] = self.c2s_count.get(client, 0) + 1
                        dropped = dropped or n in self.drop_c2s
                    if not dropped:
                        self.schedule(dest_sock, data, dest)
                    out.write(json.dumps({
                        "t": round(time.monotonic() - start, 6),
                        "dir": direction,
                        "client": self.client_ids.get(client, -1),
                        "len": len(data),
                        "dropped": dropped,
                        "hex": data.hex(),
                    }) + "\n")
                    count += 1
                self.flush_due()
            out.flush()
        print(f"tap done, {count} datagrams -> {out_path}", flush=True)
        return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--listen", type=int, required=True)
    p.add_argument("--upstream", type=int, required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--seconds", type=float, default=15.0)
    p.add_argument("--delay-ms", type=float, default=0.0, help="one-way delay per direction")
    p.add_argument("--loss", type=float, default=0.0, help="drop probability per datagram")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--drop-c2s", default="", help="comma list of 1-based c2s datagram indices to drop")
    a = p.parse_args()
    drops = frozenset(int(x) for x in a.drop_c2s.split(",") if x.strip())
    tap = Tap(a.listen, a.upstream, a.delay_ms / 1000.0, a.loss, a.seed, drops)
    return tap.run(a.out, a.seconds)


if __name__ == "__main__":
    sys.exit(main())
