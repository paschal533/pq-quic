# Phase 2 pilot: hybrid vs classical handshake latency (2026-10-26)

**Status: pilot, not paper numbers.** The point is to test the method and find problems before the
real Phase 2 runs.

## Method

- `harness/bench_handshake.py`, driven by `harness/run_pilot.sh`; runs are serial, never concurrent.
- One default listener per run (PQ-capable). The dialer is a fresh process and a fresh connection
  per dial. It times only its own `Connect` (Go) or dial → `ConnectionEstablished` (Rust).
- **Paired, interleaved:** each pair is one hybrid dial and one classical dial, in random order
  (seeded), back to back. Classical = the same binary with `GODEBUG=tlsmlkem=0` (Go) or
  `PQQUIC_CLASSICAL=1` (Rust, harness patch). The listener stays default, so classical dials
  negotiate X25519 with no HRR (C-16).
- Network impairment is inside `quic_tap.py` (userspace, Windows loopback):
  - fixed one-way delay per direction (RTT = 2 × delay)
  - independent per-datagram loss (seed 7)
- Profiles: (delay, loss) = (0, 0), (25 ms, 0), (75 ms, 0), (25 ms, 1%), (25 ms, 5%); 30 pairs each; go and rust.

## Results (`data/bench/pilot-20261026T172756Z/`, 30 pairs per row, no failed dials)

| stack | one-way delay | loss | median hybrid ms | median classical ms | median paired ratio (IQR) |
|---|---|---|---|---|---|
| go | 0 | 0 | 18.3 | 15.4 | 1.22 (0.71–1.93) |
| go | 25 | 0 | 132.5 | 131.6 | 0.99 (0.97–1.06) |
| go | 75 | 0 | 343.8 | 335.2 | 1.01 (0.96–1.06) |
| go | 25 | 1% | 129.9 | 132.3 | 0.98 (0.94–1.01) |
| go | 25 | 5% | 139.8 | 135.3 | 1.03 (0.90–1.60) |
| rust | 0 | 0 | 55.7 | 55.8 | 1.03 (0.90–1.19) |
| rust | 25 | 0 | 120.3 | 120.1 | 1.01 (0.93–1.11) |
| rust | 75 | 0 | 220.5 | 219.4 | 1.00 (0.98–1.05) |
| rust | 25 | 1% | 117.0 | 119.7 | 0.98 (0.93–1.09) |
| rust | 25 | 5% | 121.8 | 122.1 | 1.01 (0.90–1.14) |

## What the pilot says (pilot-grade, not for the paper yet)

1. **With delay and no loss, hybrid costs nothing measurable at 50 and 150 ms RTT on either stack.**
   Paired ratios are 0.99–1.01 with IQRs within about ±6%. The extra ~1.2 KB fits in the same flight,
   and the second Initial packet leaves together with the first, so no round trip is added.
2. **At 0 ms the Go ratio is 1.22, but its spread (0.71–1.93) is too wide to mean much.** That is
   the expected home of the ML-KEM CPU cost, and it is below the resolution of userspace timing on
   Windows. Use in-process microbenchmarks if this needs a number.
3. **Random loss needs far more samples.** At 5% only a few pairs per run lose a handshake packet,
   which shows up as Go's IQR tail (diff up to +80 ms) but can't be estimated from 30 pairs.
   **The better experiment is targeted loss:** drop the second ClientHello datagram (which only
   hybrid has) deterministically and measure the recovery penalty directly. This is the real Q2 question.
4. **Absolute latencies include libp2p steps above TLS**, so they are not handshake times:
   - Go is about 2.3–2.6 RTT. Hypothesis: go-libp2p's `Connect` waits for Identify (one more RTT);
     check before stating it.
   - Rust is about 1 RTT plus a fixed ~50–70 ms (55 ms even at 0 delay), cause unknown.
   - Fix for real runs: measure handshake time from the tap trace (first client Initial → client's
     first Handshake-space packet), which is the same for every stack and excludes libp2p steps.

## Known method issues (found during the pilot)

1. **Cold start:** the listener's first connection is answered about 30 ms later than the rest
   (trace `data/bench/smoke-rust.jsonl`, client 0). Pair 0 carries it. Fixed after the pilot: one
   unrecorded warm-up dial in `bench_handshake.py`.
2. **rust-libp2p reports "connected" about one RTT after the TLS handshake ends**, for classical and
   hybrid alike. In the smoke trace, the client's Initial is answered at +79 ms (tap time, 25 ms
   one-way delay), but `ConnectionEstablished` follows a further 1-RTT exchange. Explain this
   (quinn handshake confirmation? libp2p-quic upgrade step?) before quoting any absolute Rust
   latency. Ratios are unaffected because both variants pay it.
3. Userspace delay on Windows adds scheduler jitter of about a millisecond, so sub-millisecond
   differences at the 0 ms profile are not meaningful.

## Next steps for real Phase 2

- Trace-derived handshake time per connection (stack-independent).
- Targeted-loss mode in the tap: drop client Initial datagram #2 / server Initial #k, plus a run that
  drops the same index for classical as a control.
- More pairs (≥200) for random-loss profiles; Linux netem cross-check on one profile, so the
  userspace-delay tap is validated against a kernel qdisc.
