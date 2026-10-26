# Prediction recorded before the run (2026-10-27)

Run: go-libp2p with quic-go's initial RTT forced to 500 ms (first PTO = 2 × 500 = 1,000 ms, like quinn's 999 ms; checked:
classical first-packet-loss stall 1,071 ms vs 267 ms default), random loss 2/5/10%, 200 pairs, seed 23, 50 ms RTT.
Baseline: go default on the same seed: +5 / −6 / +50 ms.

If the explanation is right (C-26 inverse), go turns into rust's pattern: hybrid faster under loss, clearly negative at 2% and 5%
(rust default: −40 / −65 / +4 on this seed). If go stays positive, the explanation is incomplete.
