# Prediction recorded before the run (2026-10-27)

Run: go-libp2p with quic-go initial RTT 500 ms (first PTO 1 s) AND initial packet size 1,200 B (harness patches
`PQQUIC_INITIAL_RTT_MS=500 PQQUIC_INITIAL_PACKET_SIZE=1200`; checked: hybrid ServerHello now spans two server Initial
packets, CRYPTO 1,155 + 23 B, as in quinn). Random loss 2/5/10%, 200 pairs, seed 23, 50 ms RTT.

If C-28 is right, this go behaves like rust default: hybrid clearly faster at 2% and 5% (rust default seed 23: −40 / −65),
and hybrid stalls after loss of the server's first datagram mostly disappear. If not, C-28 is incomplete.
