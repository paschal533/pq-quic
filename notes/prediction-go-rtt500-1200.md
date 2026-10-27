# Prediction recorded before the run (2026-10-27)

Run: go-libp2p with quic-go initial RTT 500 ms (first PTO 1 s) AND initial packet size 1,200 B (harness patches
`PQQUIC_INITIAL_RTT_MS=500 PQQUIC_INITIAL_PACKET_SIZE=1200`; checked: hybrid ServerHello now spans two server Initial
packets, CRYPTO 1,155 + 23 B, as in quinn). Random loss 2/5/10%, 200 pairs, seed 23, 50 ms RTT.

If C-28 is right, this go behaves like rust default: hybrid clearly faster at 2% and 5% (rust default seed 23: −40 / −65),
and hybrid stalls after loss of the server's first datagram mostly disappear. If not, C-28 is incomplete.

## Result (randomloss-go-rtt500-1200-20261026T234643Z)

Prediction **confirmed**. Paired Connect difference, hybrid − classical (95% CI), seed 23:

| loss | go default | go 500 ms | go 500 ms + 1,200 B | rust default (seed 23 / 41) |
|---|---|---|---|---|
| 2% | +5 | −1.8 | −17.4 (−47, +12) | −40 / −33 |
| 5% | −6 | +6.1 | −54.0 (−101, −11) | −65 / −54 |
| 10% | +50 | −21.7 | −146.8 (−232, −63) | +4 / −126 |

Stall rate > 500 ms, hybrid vs classical: 0.5 vs 4.0% (2%), 2.5 vs 7.5% (5%), 9.0 vs 20.5% (10%).
Server's first datagram lost first: hybrid median Connect 211 ms (2/22 stalls) vs classical 340 ms (13/29).

With quinn's two parameters (pre-sample PTO ≈ 1 s, 1,200-B initial packets), quic-go reproduces rust's hybrid gain.
With quic-go's own (200 ms, 1,280 B), quinn reproduces go's small penalty (C-26). Both directions are now tested.
