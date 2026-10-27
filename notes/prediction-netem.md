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

## Outcome, rust (2026-10-27, run `data/bench/netem-20261027T161737Z`)

WSL2 Ubuntu-20.04, kernel 6.6.87.2-microsoft-standard-WSL2, run as root (Docker engine was down).
rust-pair built natively in WSL from the same source and lockfile.

| loss | paired mean hybrid − classical | 95% CI | stall>500ms hyb / cls |
|---|---|---|---|
| 2%  | +26.2 ms | [−7.0, +58.5]  | 4.0% / 1.5% |
| 5%  | −34.1 ms | [−95.6, +33.8] | 7.0% / 10.5% |
| 10% | +64.4 ms | [−31.6, +163.1] | 19.1% / 17.6% |

**The rust prediction fails:** two of three point estimates are positive and no CI excludes 0.
Per the rule above, the rust hybrid gain is not yet a stack property.

Open confound, not yet tested: `lo` has `tx-udp-segmentation: on` and quinn uses UDP GSO on Linux.
GSO segmentation happens after the qdisc, so a GSO batch of several datagrams reaches netem as one skb
and is kept or dropped as a unit. That breaks the "independent loss per datagram" assumption above,
and it would hit the hybrid's two-datagram ClientHello flight. quic-go also uses GSO on Linux.
Whether the peers actually batched these flights here is unverified.

### GSO check (2026-10-27, before the GSO-off rerun)

Added `PQQUIC_DISABLE_GSO=1` to the vendored libp2p-quic (`TransportConfig::enable_segmentation_offload(false)`).
Sniffed outgoing UDP on `lo` (AF_PACKET), 10 pairs, no loss, rust:
- GSO on: 475 packets on the wire, including 22 of 2400 bytes (two 1200-byte datagrams in one GSO batch).
- GSO off: 498 packets, none above 1452 bytes.

So the GSO confound is confirmed for rust: in run `netem-20261027T161737Z`, netem kept or dropped these
pairs as a unit. That run does not test the prediction. `tc -s` packet counts did not show this (1016 vs
1012), because the qdisc byte/packet counters count GSO segments, not skbs.
The prediction above is unchanged for the GSO-off rerun (`TAG=nogso`). Go gets `QUIC_GO_DISABLE_GSO=true`.

## Outcome, rust, GSO off (run `data/bench/netem-nogso-20261027T164913Z`)

| loss | paired mean hybrid − classical | 95% CI | stall>500ms hyb / cls |
|---|---|---|---|
| 2%  | −27.7 ms | [−55.0, −2.0]   | 0.0% / 3.5% |
| 5%  | +5.2 ms  | [−52.4, +75.1]  | 2.0% / 6.0% |
| 10% | −84.8 ms | [−192.0, +21.4] | 9.0% / 19.6% |

Against the prediction:
- "negative at every loss rate": **fails** (5% is +5.2, CI straddles 0).
- "CI excludes 0 in at least two of three": **fails** (only 2%).
- "stall rate higher for classical than hybrid": **holds** in all three cells (3.5 vs 0, 6.0 vs 2.0, 19.6 vs 9.0).

So the stall-rate pattern the mechanism predicts reproduces on Linux with kernel loss, but the paired mean
does not reach the stated bar. Not yet a stack property under the rule above. Unexplained: the 2% medians
(112 / 111 ms) are ~15 ms above the GSO-on run (98 / 96 ms); not investigated.

### GSO check, go (before the go run)

Same sniff, 10 pairs, no loss: largest UDP payload 1280 bytes with `QUIC_GO_DISABLE_GSO=false` and with
`=true` (343 vs 325 packets). quic-go did not GSO-batch handshake datagrams here, so GSO is not a confound
for go. The go cells still run with `QUIC_GO_DISABLE_GSO=true` to match rust.

## Outcome, go, GSO off — partial (run `data/bench/netem-nogso-20261027T170712Z`)

The run was stopped by the host during the 10% cell (Claude Code reaped it under memory pressure;
not a harness failure). 2% and 5% are complete; 10% has no data.

| loss | paired mean hybrid − classical | 95% CI | stall>500ms hyb / cls |
|---|---|---|---|
| 2%  | +4.1 ms | [−6.8, +15.2]  | 0.0% / 0.0% |
| 5%  | −3.2 ms | [−20.2, +13.6] | 1.0% / 0.5% |
| 10% | not run | | |

So far: 2% is positive as predicted (CI includes 0, which the prediction allows); 5% "may be either
sign" — consistent. The decisive go cell (10%, CI should exclude 0) is still missing.

## Outcome, go 10%, GSO off (run `data/bench/netem-nogso-20261027T202855Z`, rerun of the killed cell)

| loss | paired mean hybrid − classical | 95% CI | stall>500ms hyb / cls |
|---|---|---|---|
| 10% | +20.7 ms | [−7.6, +53.2] | 3.5% / 3.5% |

Go against the prediction:
- point estimate positive at 2% and 10%: **holds** (+4.1, +20.7).
- 10% CI excludes 0: **fails**.
- stall rate similar or higher for hybrid: **holds** (0/0, 1.0/0.5, 3.5/3.5).

## Verdict (both stacks)

Signs and stall patterns match Windows for both stacks in 5 of 6 cells (rust 5% is the exception), but
neither stack meets its stated CI bar on one 200-pair Linux run. By the rule recorded above, the
C-25..C-29 effect is not yet established as a stack property independent of the Windows setup. It is
not contradicted either: no cell is clearly against the predicted sign. Whether this is lack of power
(Windows C-25 pools 400+ pairs per cell) or a real difference is not known; a second seed would tell.
