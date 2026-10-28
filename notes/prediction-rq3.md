# Prediction recorded before the run (2026-10-28): RQ3, DCUtR hole punch with a two-datagram ClientHello

Scope decision (user, 2026-10-28): RQ3 is in scope. go-libp2p v0.51.0 only; rust is optional later.
Design and mechanism: `notes/rq3-holepunch-feasibility.md`. Written before any pilot. The pilot only
checks the setup (NAT mapping, that DCUtR runs, that the skew lands where intended), and its data is
not counted.

Run: `harness/linux/run_holepunch.sh` (WSL2 kernel 6.6.87.2, five netns, nft NAT), peer
`harness/go-pair/hp` (go-libp2p v0.51.0, vendored quic-go as in go-pair), GSO off. One-way delay
D = 100 ms on every A<->B path (direct RTT 200 ms), relay legs 50 ms one way. Skew SKEW ∈ {0, 50, 90,
110, 150, 300, 1000} ms, made by adding 2·SKEW to A→relay packets only. 100 pairs per skew, hybrid and
classical in seeded order within each pair, fresh peer processes per trial. Two router models:
`unified` (primary: masquerade, unsolicited WAN input dropped) and `testplans` (plain snat, no filter).

Roles (go-libp2p v0.51.0 `holepuncher.go:137-176`, `svc.go:240-277`): B (listener, inbound relayed
connection) initiates, waits RTT/2 and sprays as QUIC server. A (dialer over the circuit) dials as
QUIC client on SYNC, so A's ClientHello is the one that crosses B's NAT. B retries 3 times, switching to
client on the last attempt.

Metrics per trial: `direct` (A has a non-relayed connection before its 60 s timeout); `attempts`
(B's `StartHolePunch` events); `t_punch` = A's `EndHolePunch.EllapsedTime` of the successful attempt
(SYNC received at A until the direct connection is up).

Model: A's first Initial reaches B's NAT at 2D after B starts the exchange; B's mapping appears at D +
SKEW. For SKEW < D the first flight passes; for SKEW > D it is dropped and A's retransmissions decide.
Datagram 2 of a hybrid hello would only pass alone if B's mapping appeared in the gap between the two
datagrams, which on veth is expected to be microseconds wide.

Predictions (`unified` model):
1. **Success.** Hybrid and classical direct-connection rates differ by ≤ 5 percentage points at every
   skew, and no cell has a two-sided Fisher exact p < 0.05 between them.
2. **Time.** For SKEW ≤ 90, `t_punch` medians are within 20 ms of each other (hybrid − classical) and
   below 300 ms. For SKEW ≥ 110, both medians step up by at least 150 ms over the SKEW = 0 cell (a lost
   first flight, recovered by PTO; C-20 puts quic-go's first PTO near 200 ms). The hybrid − classical
   median difference stays within ±20 ms in every cell.
3. **Attempts.** The share of trials needing more than one attempt differs by ≤ 5 pp between hybrid
   and classical in every cell.

`testplans` model (descriptive, direction only): at SKEW > D both variants succeed less often, or need
more attempts, than in `unified` (an unsolicited Initial delivered to the router is confirmed in
conntrack and can clash with B's later outbound mapping). The hybrid/classical comparison uses the same
rules as 1–3.

The null is the expected result. What would refute this model: hybrid needing fewer attempts or a
shorter `t_punch` than classical at SKEW = 110 or 150 (datagram 2 getting through on its own), or any
success-rate gap at SKEW ≤ 90.

## Setup notes added before the main run (2026-10-28, after the pilot; predictions unchanged)

- **Toolchain:** the peer is built with Go 1.27.3 (the Go 1.26.10 toolchain used for C-17..C-31 is no
  longer installed), same go.mod, go-libp2p v0.51.0, vendored quic-go. Per C-32 the only wire change
  is ML-DSA entries in signature_algorithms (+16 B ClientHello), present in both variants.
- **Pilot** (3 pairs, skew 0 and 150, `unified`; not counted, kept outside `data/`): found and fixed
  two setup bugs (nft one-line chain syntax; veth naming collision with the host's eth0), then ran
  12/12 direct. It confirmed that DCUtR runs (StartHolePunch on both peers, no DirectDial), that the
  direct connection lands on the NAT's WAN address, and that the skew lands as designed (B's measured
  RTT 502 ms = 2D + 2·150). t_punch medians were ≈ 210 ms at skew 0 and ≈ 411 ms at skew 150, which is
  what the model in this note predicts. No prediction above was changed.

## Design change before the remaining cells (2026-10-28, user decision)

Recorded before running unified 300/1000 and testplans 110–1000. In `testplans`, a failed trial lasts
A's full 60 s timeout, so a failing 200-trial cell takes ≈ 3.5 h. The `testplans` cells at SKEW ≥ 110
are cut to **30 pairs** (60 trials) each; that model was registered as descriptive (direction only), so
this changes no prediction. `unified` stays at 100 pairs in every cell, and so do testplans 0/50/90
(already run). The seeded variant order for 30 pairs is the first 30 rows of the 100-pair order.

Seen before this change (reported in f20d42e): testplans 0/50/90 200/200 direct; a partial testplans
110 run (43 trials, discarded and rerun) had 0 direct for both variants, each after 3 attempts.
