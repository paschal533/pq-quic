# Prediction recorded before the run (2026-10-27, night)

Replication of C-30 with a second dial-order seed. Identical harness to C-30 (commit 4d4bc12 binaries:
WSL-built rust-pair with `PQQUIC_DISABLE_GSO=1`, gopair with `QUIC_GO_DISABLE_GSO=true`), WSL2 kernel
6.6.87.2, netem `delay 25ms loss X%` on `lo`, 200 pairs per cell, loss 2/5/10%, **seed 41**.

Primary test: the **pooled** seeds 23 + 41 (400 pairs per cell), against the unchanged criteria in
`prediction-netem.md`:
- rust: hybrid − classical negative at every loss rate; CI excludes 0 in at least two of three cells.
- go: positive at 2% and 10%; the 10% CI excludes 0; 5% either sign.
- stalls > 500 ms: classical > hybrid on rust; hybrid ≥ classical (or similar) on go.

Seed 41 alone is reported but is not the test. If pooled passes, C-25..C-29 hold on Linux for this
setup. If it fails again, the Linux and Windows effects differ in size, and the paper must report the
Windows numbers as setup-specific until the difference is explained. No further seeds will be added
to rescue a failure.

## Outcome (2026-10-28): run `data/bench/netem-nogso-seed41` is confounded; the test was not run

- **rust cells (23:2x–23:44 on 10-27) are invalid.** The whole latency distribution moved up: at 2%
  loss the minimum Connect was 149.7 ms and the median 279.5 ms, versus 86.5 / 111.6 ms with seed 23
  (`netem-nogso-20261027T164913Z`). During these cells, two Claude research agents on the same host were
  doing CPU-heavy work (decrypting traces, running proxy unit tests). That breaks the
  "never run two benchmarks at once" rule in spirit. It was the operator's scheduling error, not a
  property of the stacks.
- **go cells:** 2% ran at 23:48 (agents possibly still active); the host then slept from about 23:50
  to 08:40 (System log wake at 08:40:44); 5% and 10% ran 08:40–08:47 right after wake. go medians
  (108.5–116.6 ms) are close to seed 23's, but the run is not clean either.
- The paired seed-41 differences are therefore **not pooled** and not used for the test. They are
  kept only as a record (rust −84 / −108 / −62 ms; go +0.8 / +5.7 / −8.9 ms), and they must not be
  quoted as evidence either way.
- Next: rerun seed 41, both stacks, with nothing else running on the host and sleep disabled. That
  rerun is the replication. This is a rerun of the same pre-registered seed because of a documented
  confound, not an added seed.
