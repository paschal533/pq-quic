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
