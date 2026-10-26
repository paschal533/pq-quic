# Prediction recorded before the run (2026-10-27)

Run: go-libp2p with quic-go's initial RTT forced to 500 ms (first PTO = 2 × 500 = 1,000 ms, like quinn's 999 ms; checked:
classical first-packet-loss stall 1,071 ms vs 267 ms default), random loss 2/5/10%, 200 pairs, seed 23, 50 ms RTT.
Baseline: go default on the same seed: +5 / −6 / +50 ms.

If the explanation is right (C-26 inverse), go turns into rust's pattern: hybrid faster under loss, clearly negative at 2% and 5%
(rust default: −40 / −65 / +4 on this seed). If go stays positive, the explanation is incomplete.

## Result (randomloss-go-rtt500-20261026T232413Z)

Prediction **partly confirmed** at best. Paired Connect difference, hybrid − classical (95% CI), seed 23:

| loss | go default | go initial RTT 500 ms | predicted (rust-like, default seed 23) |
|---|---|---|---|
| 2% | +5 (−8, +18) | −1.8 (−35, +29) | −40 |
| 5% | −6 (−26, +12) | +6.1 (−52, +62) | −65 |
| 10% | +50 (+21, +78) | −21.7 (−101, +60) | +4 |

- The shift is in the predicted direction, largest at 10% (+50 → −22). The CIs are wide, though, because 1 s stalls add a lot of variance.
- Go with a long timer does **not** show rust's clear gain at 2% and 5%. Stall rate (> 500 ms) at 2%: hybrid 2.5% vs classical
  3.0% on patched go, but 0% vs 5.0% on default rust. So hybrid go dials still hit long timeouts that hybrid rust dials avoid.
- Reading: the initial timer explains go-like behaviour (C-26: making quinn's timer short reproduces go's penalty), but a long
  timer alone does not make quic-go behave like quinn. There is a second stack difference. Candidates to check in the
  traces: which packet loss causes the hybrid stalls on patched go (server Initial? client part 2?), and whether quic-go
  and quinn differ in how they treat the server ACK of ClientHello part 2 (the probe effect behind C-18).
- So the explanation in phase2-random-loss.md stands as **one-directional**. Do not state it as a full model.

## Follow-up: the second difference is datagram size on the server side (C-28)

Server Initial frames (no-loss traces): go s2c#1 = ACK + CRYPTO[0+1178], so the whole hybrid ServerHello fits in one 1,280-B
datagram. rust s2c#1 = ACK + CRYPTO[0+1147], s2c#2 = CRYPTO[1147+31]: in quinn's 1,200-B datagrams the hybrid ServerHello
spills into a second Initial packet. (Both stacks put the ACK only in the first server Initial, so that is not the difference.)

When the **server's first datagram** is the first loss:
- rust default (seed 41, all loss levels): hybrid median Finished 243 ms (7/26 over 500 ms) vs classical 1,132 ms (20/26).
- go default (seed 41): hybrid 272 vs classical 328 ms (both timers short).
- go with 500 ms initial RTT (seed 23, Connect time): hybrid 1,125 ms (18/31 over 500) vs classical 1,197 (15/27). Hybrid stalls too.

So the probe effect of C-18 works on **both** sides on quinn: the second ClientHello packet gets an ACK from the server, and the
second ServerHello packet gets an ACK from the client, and each lets the sender detect the lost first packet by time threshold.
On quic-go the client side works (C-18) but the server side does not, because the larger datagram leaves no second
ServerHello packet. With a long timer, hybrid go therefore avoids only the client-side half of the stalls. That fits C-27.

Full mechanism (strong pilot): hybrid − classical under loss = (extra packets × p × recovery cost)
− (p × first-flight stall avoided, on each side where the hello spans two packets). Two stack parameters set the sign:
the pre-sample PTO (quinn ≈ 1 s, quic-go 200 ms) and whether the hybrid ServerHello spills into a second Initial packet
(quinn 1,200-B datagrams: yes; quic-go 1,280-B: no).
