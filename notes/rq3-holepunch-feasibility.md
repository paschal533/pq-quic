# RQ3 feasibility: does a two-datagram hybrid ClientHello change DCUtR hole punching?

2026-10-27. Desk research only. Nothing was run on the network. Sources are pinned below. Anything marked **UNVERIFIED** is my reasoning or memory and has not been checked against code or a trace.

Clones in `deps/`: test-plans `0c9f70c`, unified-testing `4ade567`, specs `c750236`. go-libp2p v0.51.0 and libp2p-quic 0.14.0 come from the local module and cargo caches.

## 1. The existing interop tests

**test-plans/hole-punch-interop** (`README.md`, `src/generator.ts`, `router/run.sh`) uses six containers: redis, a rust relay, a dialer, a listener, and one router per client. Each router does plain source NAT with nftables, `snat $ADDR_EXTERNAL` on postrouting (`router/run.sh:29-31`). It has no filter rules. Delay comes from netem on both router interfaces, half on each (`run.sh`, the `half_of_delay` lines), plus netem on the relay (`generator.ts:71`). Defaults are `routerDelay = 100` and `relayDelay = 25` (`testplans.ts:79-83`), which gives a direct RTT of 200 ms. The only thing measured is `rtt_to_holepunched_peer_millis` on the new direct connection (README, "Test flow"), plus pass or fail within a 60 s compose timeout (`compose-runner.ts:31`). Implementations: rust-v0.53, go-v0.49 and js-v3.x, all with tcp and quic (`versions.ts`).

**unified-testing/hole-punch** (`README.md`, `images/linux/run.sh`, `images.yaml`) is a pure-bash runner. The router uses iptables `MASQUERADE` (`run.sh:60`) with `FORWARD` policy DROP, and it drops unsolicited WAN input (`run.sh:48,55-56`). That input drop was added so early TCP SYNs do not get answered with RST. The relay is rust-v0.56. The implementations are rust-v0.56 and nim-v2.2. I found no go or js entry. Both support quic-v1. I found no netem or `tc` call in `lib/*.sh` or the router script, even though the README calls latency "optional". The rust peer measures `handshake_plus_one_rtt` from the relay-circuit dial to the end of the first ping (`peer.rs:456-520`). That number therefore includes the relay leg and the DCUtR exchange, not only the punch.

**Neither suite runs anything per handshake.** There is no repetition, no success rate, and no control of the sync skew. Both treat each pair as a single pass or fail.

## 2. Reproducing it without Docker in WSL2

Read-only checks on the WSL kernel `6.6.87.2-microsoft-standard-WSL2`. The distro is named Ubuntu-20.04 but `/etc/os-release` reports 24.04.4:

- **Built in (`=y`):** `NET_NS`, `VETH`, `NF_CONNTRACK` (+`PROCFS`), `NF_NAT`, `NF_NAT_MASQUERADE`, `NF_TABLES`, `NFT_NAT`, `NFT_MASQ`.
- **Modules (`=m`), `.ko` files present:** `NET_SCH_NETEM` (already loaded), `NFT_CT`, `NFT_COMPAT`, `xt_MASQUERADE`, `xt_conntrack`, `iptable_nat`, `iptable_filter`, `sch_tbf`, `IFB`.
- **Tools present:** `ip`, `nft`, `tc`, `unshare`, `iptables v1.8.10 (nf_tables)`, `python3`.
- **Tools absent:** `tcpdump`, `conntrack`, `socat`. WSL has no apt access.
- **UDP conntrack timeouts:** 30 s unreplied, 120 s stream.

**Verdict: feasible on one kernel.** The topology would be five network namespaces (A-LAN, NAT-A, WAN with the relay, NAT-B, B-LAN) joined by veth pairs. NAT would use native nft `snat`/`masquerade`, which is built in. For a firewall like unified-testing's, `ct state` needs `nft_ct.ko` loaded, and loading a module is a system change.

Pitfalls:

1. **Mapping and filtering behaviour (UNVERIFIED, from memory of `nf_nat_core.c`).** Linux NAT keeps the source port when the resulting tuple is unique. In practice that gives endpoint-independent mapping. Filtering is per 5-tuple, i.e. address- and port-dependent. This is the friendly case for hole punching. Check it in the pilot from `/proc/net/nf_conntrack`.
2. **Conntrack clash (UNVERIFIED).** An unsolicited Initial that reaches a router with no input filter (the test-plans router) is delivered locally, and its conntrack entry gets confirmed. The router's own outbound punch then collides with that tuple, and NAT may remap the source port, which breaks the punch. unified-testing's input DROP happens before conntrack confirmation, so it should avoid this. The router model therefore changes the outcome. Run both models.
3. **netem placement.** netem acts on egress only. The NAT mapping is created at forward time, before the qdisc, so put delay on the WAN-side veths. The existing `harness/linux/run_netem.sh` uses netem on `lo` in the root namespace. The new topology must not touch it. Its CPU load would also disturb the timing run now in progress, so start only after that run finishes.
4. **GSO.** `notes/prediction-netem.md:43-50` shows quinn sending the two hybrid datagrams as one 2,400 B GSO skb. A NAT or netem then keeps or drops both together, and the RQ3 mechanism disappears. GSO must be off (`PQQUIC_DISABLE_GSO=1`, `QUIC_GO_DISABLE_GSO=true`).
5. **No packet capture.** tcpdump is missing. Options: copy a static tcpdump from the host, use nft `log`/`counter` rules, or log from inside the peer (qlog / `SSLKEYLOGFILE`).
6. **No DCUtR peer exists.** `harness/go-pair` and `rust-pair` do direct dials only. A new peer is needed, with a relay client, DCUtR and a relay server.

## 3. Mechanism and where two datagrams could matter

Spec (`specs/relay/DCUtR.md:76-101`): B is the inbound peer on the relayed connection. B sends `Connect`, measures the RTT, sends `Sync`, and waits RTT/2. **A dials QUIC immediately on receiving `Sync` and becomes the QUIC client.** When B's timer fires, it sprays random-byte UDP packets at A every 10–200 ms and becomes the QUIC server. B retries up to 3 attempts (`:110-111`).

go-libp2p v0.51.0 matches the spec:

- B, the initiator, waits `synTime := rtt / 2` (`holepuncher.go:150-155`) and calls `holePunchConnect(..., isClient=false)` (`:165`). QUIC `Dial` with `!isClient` runs `holePunch` (`transport.go:118`). That function sends 64 B random payloads with sleep `10 ms + rand(min(10(i+1)², 200)) ms` (`transport.go:230-248`) and gives up after `HolePunchTimeout = 5 s` (`:35`).
- A, the receiver, dials as client at once (`svc.go:273`). Its outer timeout is `defaultDirectDialTimeout = 10 s` (`svc.go:22`).
- rust's libp2p-quic 0.14.0 does the same spray: 64 B, 10–200 ms (`hole_punching.rs:30-41`).
- I did not read rust's DCUtR role code (libp2p-dcutr is not in the local cache): **UNVERIFIED**.

**Concretely**, with symmetric paths A's Initial and B's first spray packet leave at about the same time. B's NAT mapping exists almost immediately, and A's Initial reaches B's NAT one one-way delay later, so the first flight passes. The first flight is dropped at B's NAT only when B is late by a skew Δ greater than the one-way delay from A to B's NAT. Skew comes from relay-path asymmetry: extra delay X on relay→B inflates B's measured RTT without delaying `Sync`, so Δ = X/2. It can also come from RTT noise. Two cases follow:

- **Both datagrams dropped.** Classical and hybrid both wait for the client's first PTO: 200 ms for go, 999 ms for quinn (C-20). After that, B's mapping exists and the retransmit gets through. Prediction: no difference.
- **Only datagram 1 dropped.** B's mapping appears between datagram 1 and datagram 2 arriving. B's server receives datagram 2 and ACKs it. A's client then resends datagram 1 by time-threshold loss detection after about 9/8 of the RTT (C-18, C-21), not after a PTO. Classical has no datagram 2, so it waits for the PTO. The width of this window equals the gap between the two datagrams at B's NAT. On veth with GSO off that gap is probably microseconds (**UNVERIFIED**; measure it).

**Falsifiable predictions** (record them before running, as in `prediction-*.md`):

- **P1.** Hole-punch success over 200 trials per cell is the same for hybrid and classical (difference ≤ 2 pp) at every skew Δ up to 4 s. Every failure has a cause unrelated to the ClientHello: the clash, or the 5 s cap.
- **P2.** Time from `Sync` to the direct connection, as a function of Δ, is a step at Δ ≈ d(A→NAT_B). The step height is the PTO (≈200 ms go, ≈1 s rust). Hybrid and classical are the same, within ±20 ms paired median.
- **P3.** Only if datagram spacing is widened artificially (tbf/netem `rate` on A's WAN egress, e.g. 1 Mbit/s ≈ 10 ms per 1,280 B), a band of Δ about as wide as the spacing appears. Inside it, hybrid comes in about one PTO earlier than classical. With no rate limit, that band should be empty.

P1 or P2 failing at zero or small Δ would be the interesting result, and it would refute this model.

## 4. Minimal experiment and effort

- **Build.** One go-libp2p v0.51.0 binary with three roles: relay, listener-behind-NAT, and dialer. It should log the go-libp2p holepunch tracer `EndHolePunch` dt and the attempt count, and toggle classical mode with `GODEBUG=tlsmlkem=0` (C-13). Then a bash `netns` script with nft NAT, both router models, and netem on the relay veth to set Δ.
- **Sweep.** Δ ∈ {0, 50, 90, 110, 150, 300, 1000} ms around a 100 ms one-way delay. Run go first; rust is optional.
- **Size.** 2 groups × 7 Δ × 100–200 trials ≈ 2,800 trials, each ≈ 2–6 s, so ≈ 3–4 h per router model.
- **Effort.** Peer: 1–1.5 days. netns script plus validation of NAT behaviour: 1 day. Runs and analysis: 1 day. **≈ 3–4 days total.** Rust adds about 1 more day.

**Go/no-go risks.**

- go-libp2p only starts DCUtR once it holds a public address (`manet.IsPublicAddr`). test-plans pins the WAN to `11.0.0.0/8` for this reason (README).
- netns setup needs root and `modprobe nft_ct`, which is a system change.
- Capture tooling is missing.
- Running it during the current timing measurement would contaminate that measurement.
- **Most important:** the expected result is a null, by construction (P1/P2). Its value is a cheap negative result for the paper ("a larger ClientHello does not hurt DCUtR on Linux NAT"), not a new effect.
