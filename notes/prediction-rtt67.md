# Prediction recorded before the run (2026-10-27)

Run: rust-libp2p with quinn initial RTT forced to 67 ms (first PTO ≈ 200 ms, like quic-go), random loss 2/5/10%,
200 pairs, seed 23, 50 ms RTT. Baseline: same seed with the default 333 ms (C-22/C-25).

If the exposure-vs-first-loss explanation is right, rust's hybrid advantage shrinks or flips towards go's
pooled numbers (≈ +10 / +7 / +37 ms). If rust stays clearly negative, the explanation is wrong or incomplete.
