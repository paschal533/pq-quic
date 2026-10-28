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

## Outcome of the clean rerun (2026-10-28, run `data/bench/netem-nogso-seed41-clean`, 09:35–10:08)

Nothing else running on the host; sleep blocked for the run (`SetThreadExecutionState`, no settings
change). Medians 108–115 ms, in line with seed 23. Pooled seeds 23 + 41 (the pre-registered test):

| stack | loss | n | paired mean hybrid − classical | 95% CI | stall>500 hyb / cls |
|---|---|---|---|---|---|
| rust | 2%  | 400 | −32.6 | [−55.8, −12.4]  | 0.0% / 4.2% |
| rust | 5%  | 400 | −39.9 | [−81.5, +1.6]   | 2.2% / 8.8% |
| rust | 10% | 399 | −78.4 | [−142.8, −12.3] | 7.0% / 17.8% |
| go   | 2%  | 400 | +1.3  | [−7.2, +9.2]    | 0.0% / 0.0% |
| go   | 5%  | 400 | −2.3  | [−13.9, +9.3]   | 0.5% / 0.8% |
| go   | 10% | 400 | +22.3 | [+3.1, +42.2]   | 3.5% / 4.8% |

Against the criteria:
- rust negative at every loss rate: **holds**. CI excludes 0 in ≥ 2 of 3: **holds** (2%, 10%).
- go positive at 2% and 10%: **holds**. 10% CI excludes 0: **holds**. 5% either sign: −2.3, allowed.
- rust stalls classical > hybrid: **holds** in all three.
- go stalls "similar or higher for hybrid": similar (0/0, 0.5/0.8, 3.5/4.8); hybrid is slightly
  *lower*, not higher. Reported as similar, with the direction noted.

**The pooled test passes.** The sign of the hybrid-vs-classical difference under random loss reproduces
on Linux with kernel netem, so C-25 is not an artefact of Windows loopback, timer resolution or the
Python tap. Seed 41 alone (clean): rust −37.4 / −85.1 / −72.1, go −1.5 / −1.3 / +23.8.
