"""py-libp2p QUIC peer for key-exchange interop runs (fits run_pair.sh).

  listen --port P [--seconds S]   print "peer <id>", log "accepted <id>" per connection
  dial --port P --peer ID         connect over QUIC and print "handshake ok"
"""

import argparse
import sys

import trio
from multiaddr import Multiaddr

from libp2p import new_host
from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.abc import INotifee
from libp2p.peer.peerinfo import info_from_p2p_addr


class AcceptLogger(INotifee):
    async def connected(self, network, conn) -> None:
        print(f"accepted {conn.muxed_conn.peer_id}", flush=True)

    async def disconnected(self, network, conn) -> None: ...
    async def opened_stream(self, network, stream) -> None: ...
    async def closed_stream(self, network, stream) -> None: ...
    async def listen(self, network, multiaddr) -> None: ...
    async def listen_close(self, network, multiaddr) -> None: ...


async def listen(port: int, seconds: float) -> None:
    host = new_host(key_pair=create_new_key_pair(), enable_quic=True)
    host.get_network().register_notifee(AcceptLogger())
    async with host.run(listen_addrs=[Multiaddr(f"/ip4/127.0.0.1/udp/{port}/quic-v1")]):
        print(f"peer {host.get_id()}", flush=True)
        await trio.sleep(seconds)


async def dial(port: int, peer: str) -> None:
    host = new_host(key_pair=create_new_key_pair(), enable_quic=True)
    async with host.run(listen_addrs=[]):
        info = info_from_p2p_addr(Multiaddr(f"/ip4/127.0.0.1/udp/{port}/quic-v1/p2p/{peer}"))
        with trio.fail_after(10):
            await host.connect(info)
        print("handshake ok", flush=True)
        await trio.sleep(0.5)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("mode", choices=["listen", "dial"])
    p.add_argument("--port", type=int, required=True)
    p.add_argument("--peer")
    p.add_argument("--seconds", type=float, default=15.0)
    a = p.parse_args()
    if a.mode == "listen":
        trio.run(listen, a.port, a.seconds)
    else:
        trio.run(dial, a.port, a.peer)
    return 0


if __name__ == "__main__":
    sys.exit(main())
