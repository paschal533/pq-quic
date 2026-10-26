# Phase 2: targeted loss of the first client datagrams (2026-10-26)

**Status: pilot-grade (30 pairs per cell, one machine, userspace delay). The mechanism is confirmed
in packet traces; the magnitudes need the real Phase 2 runs before they go in the paper.**

## Setup

- `harness/run_targeted.sh` → `data/bench/targeted-20261026T173953Z/`.
- 25 ms one-way delay (50 ms RTT), no random loss. The tap drops exactly the n-th
  client→server datagram of **every** connection (`--drop-c2s n`), for n ∈ {none, 1, 2}.
- Paired hybrid/classical dials as in the pilot, plus a warm-up dial. The handshake time is taken
  from the trace (`tap/handshake_time.py`): first client datagram → first delivered client
  Handshake-space datagram, both in tap time. This is the same for every stack and excludes libp2p
  steps above TLS.

## Results: trace handshake time, median ms (p10–p90)

| stack | drop | hybrid | classical | what was dropped |
|---|---|---|---|---|
| go | none | 69.2 (61.6–85.0) | 70.4 (62.6–85.2) | — |
| go | #1 | **149.7** (139.4–267.6) | **268.5** (153.9–278.1) | hybrid: ClientHello part 1 · classical: the whole ClientHello |
| go | #2 | 264.2 (253.7–289.1) | 266.1 (233.1–290.7) | hybrid: ClientHello part 2 · classical: the client's Handshake flight |
| rust | none | 68.2 (60.6–74.2) | 66.9 (60.8–72.6) | — |
| rust | #1 | **147.4** (142.1–156.3) | **1,077.3** (1,071.6–1,084.2) | as above |
| rust | #2 | 271.4 (252.1–303.7) | 273.5 (250.9–301.1) | as above |

(n = 28–30 per cell; a missing value means the trace had no delivered Handshake packet for that
client within the run.)

## Mechanism (from traces, `rust-drop1.jsonl` clients 1 and 2)

- **Hybrid, part 1 lost:** part 2 reaches the server, which can't use it yet but acknowledges it
  (a 48-byte Initial ACK). The client then has an RTT sample and a gap, declares part 1 lost, and
  resends it about one RTT after the ACK (+89 ms in tap time). Recovery cost is about 1.5 RTT.
- **Classical, ClientHello lost:** nothing reaches the server, so nothing comes back. The client
  waits for its first probe timeout, which rests on the default initial RTT because no sample
  exists yet. Measured: +1,016 ms for quinn (rust-libp2p), +~200 ms for quic-go. Then it resends.
- **Hybrid, part 2 lost:** the server ACKs part 1, but a lost packet *after* the last
  acknowledged one isn't detected by the ACK. The client waits for a probe timeout, now computed
  from a real RTT sample, so it is shorter: about +200 ms on both stacks.

**Verified 2026-10-26 (C-20, C-21):**
- quinn (rust-libp2p, js-libp2p-quic): initial RTT 333 ms, so the first PTO is 999 ms, as RFC 9002 §6.2.2 recommends.
- quic-go (go-libp2p): `DefaultInitialRTT = 100 ms` and `PTO = 2 × 100 ms = 200 ms` before a sample. That is shorter than the
  RFC's 333 ms SHOULD, which is why Go's classical penalty is so much smaller.
- Hybrid part-1 loss is caught by the time threshold (9/8 × RTT after the lost packet was sent), not by a PTO.
  That is why it costs about 1.1–1.8 RTT, whatever the stack's initial-RTT default.
- Part-2 loss (the last packet in flight) can only be caught by a PTO, which now uses the measured RTT
  (≈ srtt + 4·rttvar): about 200 ms on both stacks at 50 ms RTT.

So the asymmetry is a property of RFC 9002, not of one library: a one-packet first flight has nothing
behind it to trigger time-threshold detection. Its loss always costs the pre-sample PTO, 1 s by the RFC's
recommendation. Any stack that follows the RFC default (quinn, and so rust and js libp2p) should show the
large classical penalty. quic-go's shorter default hides most of it.

## What this suggests (hypothesis for the real runs)

The two-packet PQ ClientHello is **not simply "more exposure to loss"**:
- It has twice the packets, so twice the chance that one of them is lost.
- But losing the *first* packet is cheap (≈ 1.5 RTT), because the second one acts as a probe.
- A one-packet classical ClientHello has nothing to elicit an ACK, so its loss always costs a full
  initial probe timeout. With quinn's default that is about one second.

So under random loss, hybrid may have a *lower* expected handshake penalty than classical on stacks
with a long initial timeout (quinn), and a slightly higher one on stacks with a short timeout
(quic-go). Rough expectation for a small per-packet loss rate p, from the medians above:
- rust: hybrid ≈ p·(80 + 200) ms vs classical ≈ p·1,010 ms
- go: hybrid ≈ p·(80 + 195) ms vs classical ≈ p·200 ms

This is a back-of-envelope reading, not a measurement. It should be tested with large random-loss
runs (≥ 200 pairs, several p) before anyone quotes it. If it holds, it is a counter-intuitive Q2
result worth a section: on lossy links the bigger PQ ClientHello can make first contact *faster*.

## Caveats

- One machine, Windows loopback, userspace delay; no Linux netem cross-check yet.
- Every connection loses the same packet, which is a worst case by design, not a loss model.
- Only the client's first flight was targeted. Server-flight loss (ServerHello + certificate, both
  larger in PQ) is the next case to test.
- js and Chrome were not run here. Chrome's own QUIC stack has its own timers, so it should be a
  separate cell.
