# Prediction recorded before the run (2026-10-27)

Run: rust-libp2p with quinn initial RTT forced to 67 ms (first PTO ≈ 200 ms, like quic-go), random loss 2/5/10%,
200 pairs, seed 23, 50 ms RTT. Baseline: same seed with the default 333 ms (C-22/C-25).

If the exposure-vs-first-loss explanation is right, rust's hybrid advantage shrinks or flips towards go's
pooled numbers (≈ +10 / +7 / +37 ms). If rust stays clearly negative, the explanation is wrong or incomplete.

## Result (randomloss-rust-rtt67-20261026T230550Z)

Prediction **confirmed**. Paired Connect difference, hybrid − classical (95% CI), seed 23:

| loss | rust default (333 ms) | rust initial RTT 67 ms | go pooled (C-25) |
|---|---|---|---|
| 2% | −40 (−73, −12) | +9.9 (−0.4, +19.8) | +9.5 (+0.8, +18) |
| 5% | −65 (−115, −19) | +16.4 (−0.7, +35.2) | +7 (−6, +21) |
| 10% | +4 (−91, +104) | +49.6 (+20.7, +80.3) | +37 (+20, +54) |

Changing only quinn's initial RTT turns rust's hybrid advantage into go's small hybrid penalty. The sign of the
hybrid-vs-classical difference under loss is set by the stack's pre-sample probe timeout, not by the language or library.
Inverse test still to do: quic-go with a 333 ms initial RTT should gain from hybrid, like quinn (needs a patched quic-go).
