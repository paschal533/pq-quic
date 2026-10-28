# Prediction recorded before the run (2026-10-27, night): Phase 2 cost table on Linux

Run: `harness/linux/run_profiles.sh` in WSL2 (kernel 6.6.87.2), netem on `lo`, GSO off in both stacks,
one-way delay 0 / 25 / 75 / 150 ms (RTT LAN / 50 / 150 / 300), loss 0 / 1 / 5 %, 200 pairs per cell,
seed 23, go and rust, unpatched stack defaults otherwise. Metric: dialer `elapsed_ms`, paired per
iteration. Anchors: Windows pilot (`phase2-pilot.md`, 30 pairs) and C-30.

Predictions:
1. **No loss, RTT ≥ 50 ms:** hybrid costs nothing measurable. Median of paired differences within
   ±3 ms and median paired ratio within [0.98, 1.02], both stacks, all three RTTs.
2. **No loss, LAN:** hybrid is slower by a small positive amount (ML-KEM work plus one more datagram
   each way): median paired difference > 0 and < 2 ms, both stacks.
3. **Loss 1% and 5%:** same direction as C-25/C-30 — rust paired mean hybrid − classical ≤ 0, go ≥ 0,
   at every RTT. These cells are 200 pairs and expected to be underpowered (C-30); they are
   descriptive. Only a CI excluding 0 against this direction would count as a contradiction.
4. **Stalls > 500 ms (RTT ≤ 150 ms cells):** rust classical ≥ hybrid in every lossy cell.

Failure of 1 or 2 means the "no cost without loss" statement in the paper must be qualified.

## Outcome, rust half (2026-10-28)

The sweep was stopped by the host (memory pressure) after the 12 rust cells; the 12 go cells have not
run. `data/bench/profiles-linux/rust-*.csv`, kernel 6.6.87.2, GSO off, seed 23, 200 pairs each, no
missing pairs. Metric `elapsed_ms`; bootstrap CI over the paired mean (2,000 rounds).

| one-way delay | loss | median diff | median ratio | paired mean [95% CI] | stall > 500 ms H / C |
|---|---|---|---|---|---|
| 0 | 0 | −0.43 | 0.993 | −2.8 [−6.3, +0.5] | 0.0 / 0.0 % |
| 0 | 1 % | +0.57 | 1.010 | −38.7 [−68.0, −13.7] | 0.0 / 4.0 % |
| 0 | 5 % | −1.37 | 0.975 | −45.4 [−80.4, −14.4] | 0.5 / 5.0 % |
| 25 | 0 | −0.28 | 0.997 | +0.5 [−1.2, +2.4] | 0.0 / 0.0 % |
| 25 | 1 % | +1.06 | 1.010 | −4.2 [−22.7, +8.4] | 0.0 / 1.0 % |
| 25 | 5 % | +1.16 | 1.011 | −28.8 [−78.7, +19.6] | 3.0 / 8.0 % |
| 75 | 0 | −0.03 | 1.000 | +0.4 [−1.8, +2.4] | 0.0 / 0.0 % |
| 75 | 1 % | +1.85 | 1.009 | −7.0 [−31.3, +14.5] | 1.5 / 2.0 % |
| 75 | 5 % | +1.31 | 1.007 | +30.6 [−21.1, +88.8] | 12.0 / 5.5 % |
| 150 | 0 | +0.86 | 1.002 | +0.8 [−1.1, +2.8] | 0.0 / 0.0 % |
| 150 | 1 % | −1.06 | 0.997 | +21.0 [−6.9, +51.9] | 3.5 / 0.5 % |
| 150 | 5 % | +4.66 | 1.013 | +68.0 [−18.2, +159.5] | 23.5 / 13.0 % |

Verdicts (rust only):
1. **PASS.** No loss, RTT 50/150/300: median diffs −0.28 / −0.03 / +0.86 ms, ratios 0.997–1.002.
2. **FAIL as written.** LAN, no loss: median diff −0.43 ms (ratio 0.993), not > 0. The failure is
   in the direction of *less* cost: hybrid's LAN cost is below what this setup resolves (paired mean
   −2.8 [−6.3, +0.5]). It does not weaken "no cost without loss"; it does mean "a small positive
   LAN cost" cannot be claimed from this data.
3. **No contradiction by the stated rule** (no CI excludes 0 against the predicted direction), but
   the point estimate is ≤ 0 only up to RTT 150 at 1 % and RTT 50 at 5 %. It turns positive at
   RTT 150/5 % (+30.6) and at RTT 300 (+21.0, +68.0). At LAN both CIs exclude 0 in the predicted
   direction.
4. **FAIL in one cell.** RTT 150, 5 %: hybrid 12.0 % vs classical 5.5 % over 500 ms. Holds in the
   other five lossy cells with RTT ≤ 150.

Exploratory, not pre-registered (split of slow handshakes by cell baseline = pooled median):

| cell | hybrid > base+800 | hybrid base+300..800 | classical > base+800 | classical base+300..800 |
|---|---|---|---|---|
| d25 5 % | 4 | 2 | 16 | 0 |
| d75 5 % | 3 | 21 | 11 | 0 |
| d150 1 % | 4 | 3 | 1 | 0 |
| d150 5 % | 24 | 23 | 26 | 0 |

Classical slow handshakes are all large (> base+800, consistent with quinn's ≈ 999 ms pre-sample
PTO). Hybrid has a band of moderate delays that classical never shows. A hypothesis that fits, not yet
checked with traces: when one hybrid half is lost, the server's ACK of the other half gives the client
an RTT sample, so its PTO is RTT-derived; that beats 999 ms at short RTT and stops beating it as RTT
grows, while hybrid also has one more datagram to lose. The 500 ms stall threshold counts these
moderate delays at RTT 150 and is meaningless at RTT 300 (baseline ≈ 360 ms). Testing this needs
traced cells at RTT 150/300, not new statistics on this data.
