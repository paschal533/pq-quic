# Phase 1 census: which key exchange libp2p QUIC peers agree on (2026-10-26)

Loopback on Windows 11, one handshake per cell, read from QUIC Initial packets by
`harness/tap/decode_initial.py`. Every cell maps to a trace in `data/` and a row in `CLAIMS.md`.
Rows are dialers, columns are listeners. "PQ" = X25519MLKEM768 selected, no HelloRetryRequest.

| dialer ↓ / listener → | go-libp2p 0.51.0 | rust-libp2p 0.57.1 | js-libp2p-quic 2.1.5 | py-libp2p 0.8.1 (aioquic 1.7.0) | py-libp2p 0.8.1 + aioquic#634 |
|---|---|---|---|---|---|
| go-libp2p | PQ (C-01) | PQ (C-12) | PQ (C-14) | **X25519** (C-10) | PQ (C-11) |
| rust-libp2p | PQ (C-12) | PQ (C-02) | PQ (C-14) | **X25519** (C-10) | PQ (C-11) |
| js-libp2p-quic | PQ (C-14) | PQ (C-14) | PQ (C-14) | not run | not run |
| py-libp2p (aioquic 1.7.0) | **X25519** (C-10) | **P-256** (C-10) | not run | not run | — |
| py-libp2p + aioquic#634 | PQ (C-11) | PQ (C-11) | not run | — | not run |
| Chrome 155 (WebTransport) | PQ (C-15) | not run | — | — | — |

nim-libp2p: not measured yet (see CLAIMS "Not yet measured").

## What the census says so far

1. **Every stack that can do PQ does it by default, and they all agree on the same group.** go, rust,
   js (Node) and Chrome each send two key shares (X25519MLKEM768 + X25519), so the hybrid is chosen
   with no extra round trip.
2. **Fallback is silent and costs nothing on the wire.** Against py-libp2p the PQ side sees no
   hybrid share it can use and picks X25519 or P-256 from shares already sent. No HRR, no failure,
   and no signal to either application that the connection is classical. That makes the mixed-swarm
   exposure invisible, which is a point for the paper.
3. **Server preference differs.** Facing py-libp2p's four classical shares, Go picks X25519 and
   rustls picks P-256 (C-10). Harmless, but it shows the selected group is the server's policy, not
   a protocol constant.
4. **ClientHello size.** PQ ClientHellos are 1,469–1,519 B on every PQ stack, larger than one client
   Initial datagram (1,200–1,280 B), so the ClientHello always spans two Initial packets (C-04).
   Classical baselines: 266–452 B, which fits one. This is the input to Phase 2 (cost) and Phase 3
   (hole punching).

## Still to do in Phase 1

- nim-libp2p (blocked on tooling approval).
- js ↔ py and Chrome ↔ rust cells, for completeness. No surprise expected: js and Chrome behave like rust.
- A classical-only dialer against each PQ listener (Go GODEBUG / Rust patch), to confirm "no HRR"
  from the other direction too.
