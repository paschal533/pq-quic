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
