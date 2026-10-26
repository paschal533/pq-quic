# Phase 2: random loss, 200 pairs per cell (2026-10-26)

**Status: first full-size run. One machine, Windows loopback, userspace tap. Treat as strong pilot.**

Run: `harness/run_randomloss.sh` → `data/bench/randomloss-20261026T210107Z/`. 25 ms one-way delay (50 ms RTT),
independent per-datagram loss in **both** directions (tap RNG seed 23), 200 paired hybrid/classical dials per cell,
warm-up dial discarded. All 2,400 dials completed. The listener accepted every dial (401/401) except rust 10% (398/401).
Analysis: `harness/analyse_loss.py --metric elapsed_ms`.

## Primary metric: dialer Connect time (user-visible), ms

| stack | loss | hybrid mean | classical mean | paired mean diff (95% bootstrap CI) | dials > 500 ms, hybrid / classical |
|---|---|---|---|---|---|
| rust | 2% | 134 | 174 | **−40 (−73, −12)** | 0% / 5.0% |
| rust | 5% | 161 | 226 | **−65 (−115, −19)** | 1.0% / 10.0% |
| rust | 10% | 334 | 330 | +4 (−91, +104) | 11.5% / 17.5% |
| go | 2% | 158 | 153 | +5 (−8, +18) | 1.0% / 0% |
| go | 5% | 185 | 191 | −6 (−26, +12) | 0.5% / 2.0% |
| go | 10% | 276 | 226 | **+50 (+21, +78)** | 8.5% / 4.0% |

Medians are equal in every cell except go 10% (256 vs 139) and rust 10% (129 vs 115). The effect lives in the tail.

## Reading

- **rust (quinn, 1 s first PTO):** at 2–5% loss, hybrid connects faster on average. The classical stall rate
  (> 500 ms, which means waiting for the 999 ms pre-sample PTO, C-20) is 5–10× hybrid's. This is the C-18
  mechanism showing up under random loss, as predicted. At 10% both stall often, and the difference is lost in the noise.
- **go (quic-go, 200 ms first PTO):** no difference at 2–5%. At 10%, hybrid is slower by about 50 ms on average.
  The extra time does **not** show up in either trace marker (below), so it is after the client's first Handshake
  packet. Candidates: loss in the larger hybrid server flight (3 vs 2 server Initial datagrams), or post-handshake
  libp2p steps. **Unexplained. Needs Handshake-packet decryption (key log) to locate.**

## Trace metrics and why they are not the headline

- `trace_hs_ms` (first delivered client Handshake packet) can be just an ACK sent before the whole server flight has arrived. It misses server-flight loss.
- `trace_complete_ms` (first client 1-RTT packet, sent) is not a completion marker either. rust-libp2p can report
  "connected" and exit before sending any 1-RTT packet, so the marker sometimes falls after Connect returned
  (negative gaps). The client's Finished is inside encrypted Handshake packets.
- Fix: TLS key logging in the Go and Rust harnesses (Go `tls.Config.KeyLogWriter`; rustls `KeyLogFile` in the vendored
  libp2p-tls), plus Handshake-space decryption in `decode_initial.py`. Then client Finished is visible directly.
- Missing trace rows at the end of each run came from the tap being killed before flushing. Fixed (flush every loop).
  They were unbiased: the last pairs, in both variants.

## Next

1. Key log + Handshake decryption → true handshake-complete time, and an explanation for go 10%.
2. Repeat with a different seed (and more pairs for the 10% cells, where the CIs are wide).
3. Linux netem cross-check of one cell.
