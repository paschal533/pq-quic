# Prediction recorded before the run (2026-10-27)

Run: Linux cross-check. Same peers (go-libp2p and rust-libp2p, unpatched defaults), built for Linux in
Docker (`harness/linux/Dockerfile`), same bench in `--direct` mode. Impairment by kernel netem on `lo`
(`delay 25ms loss X%`) in place of the userspace tap (`quic_tap.py`). On `lo` every datagram passes one
netem qdisc once, so this is the same model as the tap: 25 ms one-way delay, independent loss X per
datagram in each direction. 200 pairs per cell, dial order seed 23, loss 2/5/10%. Metric: dialer Connect
time (`elapsed_ms`), paired mean hybrid − classical with 95% bootstrap CI. netem's loss draws are not
seedable, so cells are not draw-for-draw comparable with the Windows runs, only distributionally.

Windows baseline (C-25, pooled): rust −36 / −59 / −61 ms, go +9.5 / +7 / +37 ms.

If the C-25..C-29 mechanism is a property of the stacks (pre-sample PTO and hello packet counts) and not of
Windows loopback, timer resolution or the Python tap:

- rust: hybrid − classical is negative at every loss rate, and the CI excludes 0 in at least two of three cells.
- go: point estimate positive at 2% and 10%, with the 10% CI excluding 0; 5% may be either sign.
- Stall rate (> 500 ms) higher for classical than hybrid on rust; similar or higher for hybrid on go.

Any of these failing (especially rust ≥ 0, or go clearly negative) means the effect depends on the
Windows setup and must not go in the paper as a stack property until explained.
