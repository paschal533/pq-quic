# Post-Quantum Key Exchange Is Already On in libp2p QUIC: What the Two-Datagram ClientHello Changes

**Paschal Okwuosa** · Independent · DRAFT 2026-10-28 (Claude-drafted from `CLAIMS.md`; author to revise)

> Drafting rule: every number in this paper is a row of `CLAIMS.md` and is cited as (C-nn).
> Anything else is labelled as a projection, a hypothesis or planned work. Bracketed `[TODO …]`
> items must be resolved before submission.

## Abstract

libp2p secures its QUIC connections with TLS 1.3, and its specification leaves the choice of key
exchange group to each TLS library. We find that the defaults have already made the decision. In a
census of the five libp2p QUIC implementations and a browser, go-libp2p, rust-libp2p, js-libp2p,
nim-libp2p and Chrome's WebTransport all negotiate the hybrid group X25519MLKEM768 with no
configuration. py-libp2p does so after a single change to its QUIC library. The hybrid ClientHello is
about 1.5 KB, so it always spans two QUIC Initial datagrams instead of one. We ask what that second
datagram changes.

Without loss, it changes nothing measurable. On a LAN and at round-trip times of 50, 150 and 300 ms,
the paired hybrid and classical handshake times agree to within a millisecond. Under packet loss, the
answer depends on the transport's loss-recovery timers rather than on the cryptography. On
rust-libp2p (quinn), the hybrid handshake is *faster* on average than the classical one on Linux: by 33 ms at 2 % loss and 78 ms at 10 %
(both confidence intervals exclude zero; at 5 % the interval just includes it). Classical dials stall
beyond 500 ms 2.5–4 times as often at 5–10 % loss, and hybrid dials never did at 2 %. The
second datagram draws an early acknowledgement from the server, which lets the client detect a lost
first datagram in about one round trip instead of waiting out quinn's 999 ms initial probe timeout.
On go-libp2p (quic-go), whose initial probe timeout is 200 ms, there is no such gain, and at 10 %
loss the hybrid handshake is slower. Swapping the timer settings between the stacks moves the effect
with them. A replication on Linux kernel netem, with predictions committed before the run, confirmed
the cross-stack result. A live on-path attacker that strips or forces away the hybrid group never
obtains a classical session.

All peers, traces, benchmark data and analysis scripts are public, and every reported number is
traceable to a claims file that links its evidence.

## 1. Introduction

Peer-to-peer networks carry traffic whose confidentiality outlives the connection: consensus
messages, routing queries, storage deals. Traffic recorded today can be decrypted once a quantum
computer exists, the "store now, decrypt later" threat. That makes post-quantum key exchange urgent
even while post-quantum authentication can wait. libp2p, the networking stack under Ethereum's
consensus layer, IPFS and Filecoin, has two secure channels. One is Noise over TCP, which needs
protocol work to become post-quantum; our companion paper on Noise XXhfs covers it. The other is
QUIC with TLS 1.3, which inherits whatever the TLS library does.

The libp2p TLS specification fixes TLS 1.3, a single self-signed certificate and an identity
extension, but names no key exchange groups. So the post-quantum status of libp2p QUIC is decided
by five TLS stacks in four languages, and nobody has written down what they decided. This paper
measures it, and then asks the question that follows. A hybrid ClientHello is too large for one QUIC
Initial datagram. What does a two-datagram first flight do to connection setup on a peer-to-peer
network, where loss is common, NAT traversal depends on timing, and connections are short-lived?

**Contributions.**

1. **A census** of hybrid key exchange across all five libp2p QUIC stacks and Chrome WebTransport,
   decoded from the wire, including mixed classical/hybrid pairs, HelloRetryRequest behaviour and the
   Go 1.27 change (§5).
2. **A cost measurement without loss**, from LAN to 300 ms RTT, with paired, interleaved samples (§6).
3. **The loss result and its mechanism.** Under loss the hybrid hello helps quinn and does not help
   quic-go. We trace this to RFC 9002 time-threshold detection versus each stack's initial probe
   timeout, and confirm it with causal timer swaps in both directions and a pre-registered
   replication on a second loss emulator (§7).
4. **A live downgrade test** of hybrid negotiation in libp2p QUIC (§8).
5. **A sizing analysis of post-quantum authentication** against QUIC's anti-amplification limit for
   libp2p's mutual-authentication case (§9, a projection, not a measurement), and **a pre-registered
   hole-punching experiment** (§10, in progress).

We also report what went wrong. One cross-check failed its pre-registered bar (§7.5). One LAN
prediction was wrong (§6). A Linux send optimisation silently invalidated a run until we found it
(§4.4).

## 2. Background

**libp2p over QUIC.** A libp2p QUIC connection is an ordinary QUIC v1 connection with TLS 1.3, ALPN
`libp2p` and mutual authentication. Each side presents one self-signed certificate. Its extension
(OID 1.3.6.1.4.1.53594.1.1) carries the peer's identity key and that key's signature over the
certificate's public key. The specification does not mention key exchange groups.

**Hybrid key exchange in TLS 1.3.** RFC 10024 defines X25519MLKEM768 (codepoint 0x11EC). The client
key share is 1,216 bytes: an ML-KEM-768 encapsulation key of 1,184 bytes plus a 32-byte X25519 share.
RFC 9954 frames each hybrid as an ordinary named group, so negotiation inherits TLS 1.3's transcript
protection.

**QUIC's first flight.** RFC 9001 §4.3 allows a ClientHello to span several Initial packets. QUIC
originally required a single packet, and that rule was dropped in 2019 explicitly to make room for
post-quantum experiments. Before the client's address is validated, a server may send at most three
times the bytes it has received (RFC 9000 §8.1).

**Loss recovery before the first RTT sample.** RFC 9002 detects loss either from acknowledgements of
later packets (packet threshold, or time threshold at 9/8 of the RTT) or by a probe timeout (PTO).
Before any RTT sample exists, the PTO comes from a configured initial RTT. quinn uses 333 ms, giving
a first PTO of 999 ms, which matches the RFC's "handshakes starting with a PTO of 1 second". quic-go
uses 100 ms, giving 200 ms. Neither libp2p stack overrides these values (C-20).

## 3. Related Work

*[TODO author: tighten; every entry below was opened during the review in `notes/related-work.md`.]*

**Post-quantum QUIC performance.** Kempf et al. measure LSQUIC and quiche with liboqs-based BoringSSL
on bare metal, without emulated RTT or loss. They find Kyber, Dilithium and Falcon cheap and SPHINCS+
expensive, and they observe the amplification limit (IFIP Networking 2024). Montenegro-Montes et al.
compare PQ handshakes in TLS and QUIC under loss and delay. They report the highest overhead for
hybrid KEMs and that QUIC softens the penalty (Computer Networks 2026). Neither studies peer-to-peer
stacks, mutual authentication or the two-Initial effect in isolation. Kampanakis's slides and QUIC WG
messages discuss the amplification window and PQ signatures. Nawrocki et al. show that about 35 % of
WebPKI certificate chains already exceed the amplification limit (CoNEXT 2022).

**Deployment.** Wickramasinghe et al. scan more than 2 billion TLS-over-TCP handshakes. They find
deployment converging on X25519MLKEM768, with a median hybrid-minus-classical handshake time of 0 ms
(IMC 2026). Westerbaan's Cloudflare measurements show where large handshakes start to fail.
tldr.fail documents servers that break on split ClientHellos over TCP. Google's QUICHE "Chaos
Protection v2" commit notes that post-quantum keys made the ClientHello span several packets. Go
enabled X25519MLKEM768 by default in 1.24. None of these covers libp2p or peer-to-peer QUIC.

**NAT traversal.** Trautwein et al. measure 4.4 million DCUtR hole-punch attempts in IPFS: about 70 %
conditional success, with TCP and QUIC indistinguishable (IMC 2026). ProbeLab audits DCUtR across NAT
types. Neither considers handshake size. Post-quantum WireGuard designs avoided multi-packet
handshakes entirely.

**Post-quantum Noise.** See the companion paper and its related work (SecITC 2024 hybrid Noise on
mobile; NoisePQC++).

To our knowledge, and checked against the sources above, no prior work censuses post-quantum key
exchange in libp2p or isolates the effect of a two-datagram ClientHello on loss recovery.

## 4. Method

### 4.1 Peers and versions

We use minimal listener and dialer peers per stack: go-libp2p v0.51.0 (quic-go v0.64.1, Go 1.26.10),
rust-libp2p 0.57.1 (libp2p-quic 0.14.0, rustls with aws-lc-rs), js-libp2p 3.5.1 with
@chainsafe/libp2p-quic 2.1.5 on Node 22.17.1, nim-libp2p master 881082e (lsquic 0.11.2, BoringSSL),
py-libp2p 0.8.1 on aioquic, and Chrome 155 WebTransport (C-01, C-02, C-10, C-14, C-15, C-24). Each
dial runs in a fresh process with a fresh connection.

The classical baselines run on the same builds. For Go we set `GODEBUG=tlsmlkem=0`. For Rust a
vendored-patch switch restricts rustls to X25519 (C-13). Three further harness patches change one
transport parameter each (initial RTT, initial packet size, GSO), and they are used only in the
experiments that name them.

### 4.2 Observation

A UDP tap sits between dialer and listener. It forwards datagrams, logs them, and applies seeded
per-datagram loss and delay in each direction. A decoder derives Initial keys (checked against RFC
9001 Appendix A) and reconstructs the ClientHello and ServerHello. For selected runs the peers write
TLS key logs, so that Handshake packets can be decrypted too.

### 4.3 Benchmark design

Each *pair* is one hybrid and one classical dial, in a seeded random order, back to back, against
the same listener. Machine drift is therefore common to both members of a pair, and we report the
paired difference (hybrid − classical): its median, its mean with a 95 % bootstrap confidence
interval, and the share of dials slower than 500 ms ("stalls"). The metric is the dialer's own
connect time. Cells have 200 pairs unless stated. We never ran two benchmarks at once. One run that
overlapped other CPU load and a host sleep is recorded as invalid and excluded (C-31).

### 4.4 Two loss emulators, and a pitfall

The first results come from the userspace tap on Windows. The replication uses Linux kernel netem on
the loopback interface (WSL2, kernel 6.6.87.2), where every datagram passes one netem queue once.

The pitfall is UDP segmentation offload (GSO). On Linux, quinn hands the two 1,200-byte halves of a
hybrid hello to the kernel as one 2,400-byte batch, and netem on loopback keeps or drops that batch
as a unit. This silently removes the very effect under study. `tc` statistics count segments, so they
do not reveal it; we found it with a packet-socket capture. All netem runs therefore disable GSO in
both stacks. quic-go did not batch handshake datagrams. The Windows tap receives single datagrams:
across about 103,000 datagrams in the tap traces, none exceeds 1,452 bytes (CLAIMS method notes).

### 4.5 Pre-registration and grading

Before each confirmatory run we committed a prediction with explicit pass criteria
(`notes/prediction-*.md`), and we record outcomes against it, including failures. Claims are graded
*verified* (deterministic, from traces or source), *strong pilot* (200 pairs or more, CI reported),
or *pilot* (30 pairs, or a cross-check that has not passed).

## 5. Census: Who Already Speaks Hybrid

*[TODO: Table 1 — stack × offered groups × key shares × ClientHello bytes × selected group, from C-01, C-02, C-12, C-14, C-15, C-24, C-10, C-11, C-13.]*

- **go-libp2p** offers X25519MLKEM768, SecP256r1MLKEM768, SecP384r1MLKEM1024, X25519, secp256r1,
  secp384r1 and secp521r1. It sends two key shares (1,216 B hybrid + 32 B X25519) in a 1,511-byte
  ClientHello. The server selects X25519MLKEM768 with a 1,120-byte share and no HelloRetryRequest
  (C-01).
- **rust-libp2p** offers X25519MLKEM768, X25519, secp256r1 and secp384r1, with the same two shares,
  in 1,495 bytes, and selects the hybrid (C-02). Go and Rust interoperate on the hybrid in both
  directions (C-12).
- **js-libp2p** (@chainsafe/libp2p-quic, which uses quinn) and **nim-libp2p** (lsquic, BoringSSL)
  behave the same way. Their ClientHellos are 1,484–1,491 and 1,446 bytes, and they select the hybrid
  with every other stack in both directions (C-14, C-24).
- **Chrome WebTransport** to a go-libp2p listener offers the hybrid first in 1,469 bytes, and Go
  selects it (C-15).
- **py-libp2p 0.8.1** on aioquic 1.7.0 offers only classical groups, in 452 bytes, and every pair
  falls back to classical (C-10). Replacing aioquic with PR #634, with no change to py-libp2p, makes
  all four pairs hybrid (C-11).
- **The hybrid ClientHello spans two Initial datagrams.** This is decoded in the Go and Rust traces,
  whose datagrams are 1,280 and 1,200 bytes (C-04). Every hybrid ClientHello we measured is at least
  1,446 bytes (C-24).
- **Mixed networks.** A classical-only dialer reaching a default hybrid listener gets X25519 with no
  HelloRetryRequest, because the hybrid listener accepts the classical share it was offered (C-16).
- **Go 1.27** selects the same groups. Its dialer now lists ML-DSA-44/65/87 first in
  signature_algorithms, which adds 16 bytes. go-libp2p still signs with a P-256 certificate key, so
  no ML-DSA signature is sent (C-32).

The baseline classical ClientHellos are 287 bytes (Go) and 266 bytes (Rust) (C-13).

## 6. Cost Without Loss

Over a 30-pair pilot at 50 and 150 ms RTT, the median paired ratios were 0.99–1.01 (C-17). The Linux
cost table (200 pairs per cell, rust half complete) agrees and extends this. The median paired
difference is within ±1 ms on a LAN and at 50, 150 and 300 ms RTT, with ratios of 0.993–1.002 (C-34).

We had predicted a small positive LAN cost, below 2 ms, from the ML-KEM work and one more datagram
each way. It was not observed. The LAN median difference was −0.43 ms, and the paired mean was
−2.8 ms (95 % CI −6.3, +0.5). The failure is in the direction of *less* cost. On this setup the
hybrid's LAN cost is below what we can resolve.
*[TODO: add the go half of C-34 when the run completes on 10-28.]*

With no loss, the hybrid connection carries about one extra datagram each way (go: 8.7 versus 7.6
client-to-server, 7.5 versus 6.6 server-to-client) (C-25).

## 7. Under Loss: The Transport Decides

### 7.1 One lost datagram, by construction

We first drop exactly one chosen client datagram in every connection, at 50 ms RTT (C-18, C-19,
C-21).

- **Losing the first client datagram.** The hybrid median handshake time is 149.7 ms (Go) and
  147.4 ms (Rust). Classical is 268.5 ms and 1,077.3 ms, against no-drop baselines of 66.9–70.4 ms
  (C-18). The traces show why. The hybrid's second ClientHello datagram reaches the server, which
  acknowledges it. The client can then declare the first datagram lost by RFC 9002 time-threshold
  detection (9/8 × RTT): it resends at +81–89 ms, where the rule predicts about +73 ms (C-21). The
  classical client has nothing acknowledged, so it waits for its first PTO. On quinn that takes about
  one second (resends at +1,010–1,016 ms), and on quic-go about 200 ms (C-18, C-20).
- **Losing the second client datagram** gives no such signal. Nothing after it is acknowledged, so
  the hybrid client also waits for a PTO: 264.2 ms (Go) and 271.4 ms (Rust) (C-19).
- **The server side.** In quinn's 1,200-byte datagrams the hybrid ServerHello (1,178 bytes) spills
  into a second server Initial packet. In quic-go's 1,280-byte datagrams it fits in one. When the
  server's first datagram is the one lost, Rust's hybrid recovers in a median 243 ms against 1,132 ms
  for classical (C-28).

The second datagram is therefore a cheap early-warning signal. It pays off exactly when the transport
would otherwise fall back on a long initial PTO.

### 7.2 Random loss

With independent random loss in both directions at 50 ms RTT, the pooled paired differences are as
follows (C-25):

| loss | rust (quinn) hybrid − classical, ms [95 % CI] | go (quic-go) |
|---|---|---|
| 2 % | −36 [−59, −15] | +9.5 [+0.8, +18] |
| 5 % | −59 [−98, −23] | +7 [−6, +21] |
| 10 % | −61 [−122, −1] | +37 [+20, +54] |

On rust, dials over 500 ms fell from 5.0 % to 0 % at 2 % loss, and from 10.0 % to 1.0 % at 5 %
(seed 23, C-22). On go, the hybrid is slower at 10 % loss, with medians of 256 versus 139 ms in the
first run (C-23). We have not explained the go slowdown. It is not visible in the client's first
Handshake packet, and go's qlog shows equal RTT estimates for both variants (C-23, C-25).

### 7.3 Swapping the timers

If the initial PTO is the cause, giving quinn quic-go's timer should erase rust's gain. We forced
quinn's initial RTT to 67 ms, for a first PTO of about 200 ms. On the same seed the rust differences
moved from −40 / −65 / +4 ms to +9.9 / +16.4 / +49.6 ms at 2/5/10 % (C-26). The prediction was
committed before the run. The gain disappears, and at 10 % the rust hybrid becomes slower, as go's is.

The inverse is only partly true. Giving quic-go a 1,000 ms first PTO moved its 10 % result the
predicted way (−21.7 ms), but its confidence intervals all span zero and it does not reproduce rust's
clear gain at 2–5 % (C-27). The server-side effect explains the gap: with 1,280-byte datagrams the go
server's hybrid ServerHello fits in one packet, so go loses the second early-warning signal (C-28).
Setting quic-go's initial packet size to 1,200 bytes as well reproduced the rust pattern: −17.4,
−54.0 and −146.8 ms (CI −232, −63) at 2/5/10 % loss, with stalls of 0.5 / 2.5 / 9.0 % for hybrid
against 4.0 / 7.5 / 20.5 % for classical (C-29). The effect is a property of the transport
configuration, and moving that configuration moves the effect in both directions.

### 7.4 Replication on a second emulator

All of the above used one machine and one userspace tap. We repeated the unpatched comparison with
Linux kernel netem (§4.4).

The first Linux run, seed 23, matched the Windows signs and stall pattern in 5 of 6 cells. However,
neither stack met the confidence-interval bar we had set in advance, so we recorded it as *not
passed* (C-30). We then pre-registered a second seed and pooled the two (400 pairs per cell):

| loss | rust hybrid − classical, ms [95 % CI] | stalls hybrid / classical | go | stalls |
|---|---|---|---|---|
| 2 % | −32.6 [−56, −12] | 0 / 4.2 % | +1.3 [−7, +9] | 0 / 0 % |
| 5 % | −39.9 [−82, +2] | 2.2 / 8.8 % | −2.3 [−14, +9] | 0.5 / 0.8 % |
| 10 % | −78.4 [−143, −12] | 7.0 / 17.8 % | +22.3 [+3, +42] | 3.5 / 4.8 % |

Every pre-registered criterion held (C-31).

### 7.5 Round-trip time matters too

The Linux cost table adds loss at four RTTs (rust half, C-34). Hybrid's paired-mean advantage is
clear on a LAN: −38.7 ms (CI −68.0, −13.7) at 1 % loss and −45.4 ms (−80.4, −14.4) at 5 %. The point
estimate shrinks as RTT grows and turns positive at 300 ms RTT (+68.0 ms at 5 %), though with a CI
that includes zero. Our pre-registered stall prediction failed in one cell (150 ms RTT, 5 % loss).

A post-hoc split of slow handshakes suggests why. Classical slow handshakes are all slow by more than
800 ms, consistent with quinn's one-second PTO. Hybrid shows a band of moderate delays that classical
never shows. **Hypothesis, not yet tested:** after a partial loss, the hybrid client's PTO is derived
from a real RTT sample. That beats one second on short paths and stops beating it on long ones,
while the hybrid also has one more datagram to lose. Testing this needs traced runs at 150 and 300 ms
RTT. *[TODO: go half of C-34.]*

## 8. Downgrade

Hybrid groups are ordinary TLS 1.3 named groups, so an attacker who rewrites the ClientHello breaks
the transcript. We checked that this holds in practice. An on-path proxy rewrote the reassembled
ClientHello in go↔go and rust↔rust connections (C-33):

- **strip** removes X25519MLKEM768 from supported_groups and key_share. The rust server selects
  X25519, and the handshake then fails on the transcript mismatch. The go server sends a
  HelloRetryRequest for the still-offered SecP256r1MLKEM768. The client answers with a hybrid share
  and the handshake times out.
- **hrr-force** leaves only classical groups and an empty key_share. Both servers send an HRR for
  X25519. Both clients abort at once, as RFC 8446 §4.2.8 requires, because X25519 was already among
  their shares. Go reports "unnecessary HelloRetryRequest key_share" and Rust reports
  IllegalHelloRetryRequestWithOfferedGroup.

In all four runs every ClientHello offered X25519MLKEM768 first. No classical-only retry occurred
and no session was established (C-33). An attacker can therefore deny service but cannot downgrade.

## 9. Outlook: Post-Quantum Authentication (projection)

*This section is desk analysis on measured flight sizes (`notes/rq4-auth-sizing.md`). Its
projected sizes are arithmetic from FIPS 204 constants, not measurements.*

libp2p authentication is a chain of two signatures: the identity key signs the certificate key, and
the certificate key signs the handshake. A quantum attacker can break either link, and both stacks
reuse one certificate key for the life of the transport. A post-quantum identity key with a
classical certificate key therefore buys nothing against an active quantum attacker; both must
migrate. Because libp2p authenticates mutually, the client also sends the large Certificate and
CertificateVerify messages.

Against QUIC's 3× pre-validation budget, today's server flight fits easily. An ML-DSA-44 identity
over a P-256 certificate key (≈4.7 KB of server flight after a classical hello, ≈5.9 KB after a
hybrid one) does not fit the 3,840-byte budget that a
classical ClientHello earns. It does fit the 7,680 bytes earned by a two-datagram hybrid ClientHello.
In that narrow sense the hybrid hello is partly self-financing. Fully post-quantum configurations
(ML-DSA-44 and above for both keys, ≈11–21 KB) exceed either budget and cost one extra round trip.
*[TODO author: decide whether to keep this section, given the length.]*

## 10. Hole Punching (in progress)

libp2p's DCUtR protocol synchronises a simultaneous open across two NATs using an RTT measured over
a relay. On QUIC, the peer that dials as client sends the ClientHello through the other peer's NAT.
If the other peer is late to open its mapping, part of the first flight may be dropped. Under our
model a two-datagram hello neither helps nor hurts, except in a window that should be microseconds
wide. We pre-registered predictions to that effect (`notes/prediction-rq3.md`, committed before any
run) and built a five-namespace NAT testbed with two router models and controlled timing skew
(`harness/linux/run_holepunch.sh`). Results are not part of this submission.
*[TODO: replace with results if available by submission.]*

## 11. Limitations and Threats to Validity

- **Emulated networks only.** All runs are on one machine, on loopback, with a userspace tap
  (Windows) or kernel netem (WSL2). There are no real WAN paths, no bursty or correlated loss, and no
  reordering. Netem's loss draws are not seedable; our seeds fix only the dial order.
- **Two stacks for timing.** The timing results cover go-libp2p and rust-libp2p. js-libp2p shares
  quinn and so is expected to behave like rust, but this was not measured.
- **Effect sizes are wide.** Several 5 % cells have confidence intervals that include zero, and the
  go slowdown at 10 % loss is unexplained (C-23, C-25).
- **The inverse timer swap is partial** until the server packet size is also changed (C-27, C-29).
- **Pilot grades.** C-17, C-18 and C-19 rest on 30 pairs.
- **Version drift.** The timing results use Go 1.26.10. Go 1.27 changes only signature_algorithms
  (C-32).
- **What we did not measure:** CPU cost on constrained devices; PQ authentication beyond projection;
  middleboxes on real paths.

## 12. What This Means for libp2p

*[TODO author: these are recommendations drawn from the results; phrase in your own voice.]*

1. Post-quantum key exchange on libp2p QUIC needs no specification change to be deployed. It is the
   default almost everywhere today. py-libp2p is the exception, and closes once aioquic PR #634 lands.
2. The specification could still name X25519MLKEM768 as recommended, so that the property survives
   changes to a library's defaults.
3. Loss-recovery configuration matters more than the KEM. A one-second initial PTO makes classical
   handshakes fragile on lossy links, and the hybrid hello improves them by accident.
4. Post-quantum authentication, not key exchange, is where the wire cost and the amplification
   problem will be.

## 13. Conclusion

The question "should libp2p adopt post-quantum key exchange on QUIC?" has been answered by its TLS
libraries. The hybrid group is negotiated by default in every libp2p QUIC stack we tested except
Python's, which needs one dependency change. The cost is invisible without loss. Under loss the
outcome depends on the transport: the two-datagram ClientHello helps when the transport would
otherwise wait out a long initial probe timeout, and it does not when the probe timeout is already
short. We showed this in both directions and replicated it on a second loss emulator. The open
problems are post-quantum authentication and real-network validation.

## Artifact Availability

https://github.com/paschal533/pq-quic. The repository contains the
peers, the tap and decoder, the benchmark and analysis scripts, the traces and CSVs, every
pre-registered prediction with its commit, and `CLAIMS.md`, which maps each number in this paper to
its evidence. MIT / Apache-2.0.

## Use of AI Assistance

*[TODO author: write in your own words, e.g. which parts Claude drafted (this text, from `CLAIMS.md`)
and assisted with (harness code, analysis scripts), and that every number was checked against the
data.]*

## References

*[TODO: format. All entries below were opened during the related-work review except where noted.]*

- RFC 8446, The Transport Layer Security (TLS) Protocol Version 1.3. §4.2.8.
- RFC 9000, QUIC: A UDP-Based Multiplexed and Secure Transport. §8.1.
- RFC 9001, Using TLS to Secure QUIC. §4.3.
- RFC 9002, QUIC Loss Detection and Congestion Control. §6.1, §6.2.2.
- RFC 9954, Hybrid Key Exchange in TLS 1.3 (Stebila, Fluhrer, Gueron), 2026.
- RFC 10024, Post-quantum hybrid ECDHE-MLKEM Key Agreement for TLSv1.3 (Kwiatkowski, Kampanakis, Westerbaan, Stebila), 2026.
- FIPS 204, Module-Lattice-Based Digital Signature Standard.
- libp2p specs, tls/tls.md.
- quicwg/base-drafts PR #3045, "Allow ClientHello to span multiple QUIC packets", 2019.
- M. Kempf et al., "A Quantum of QUIC: Dissecting Cryptography with Post-Quantum Insights", IFIP Networking 2024, arXiv:2405.09264.
- J. Montenegro-Montes et al., "Comparative analysis of post-quantum handshake performance in QUIC and TLS protocols", Computer Networks 275 (2026) 111957 (abstract read).
- M. Nawrocki et al., "On the Interplay between TLS Certificates and QUIC Performance", CoNEXT 2022.
- P. Kampanakis, "The effects of Dilithium on QUIC's performance", ETSI/IQC 2023 (slides).
- B. Westerbaan, "Sizing Up Post-Quantum Signatures", Cloudflare, 2021; "The state of the post-quantum Internet", 2024.
- Wickramasinghe et al., "Mind the Gap: Policy vs Reality in Post-Quantum TLS Deployment", IMC 2026, arXiv:2607.29005.
- tldr.fail; Google QUICHE commit 54f2123 ("Chaos Protection v2"); Go 1.24 release notes.
- D. Trautwein et al., "Large-Scale Measurement of NAT Traversal for the Decentralized Web: A Case Study of DCUtR in IPFS", IMC 2026, arXiv:2604.12484.
- S. Rene, "Can libp2p punch through NATs?", ProbeLab, 2026.
- M. Seemann, M. Inden, D. Vyzovitis, "Decentralized Hole Punching", DINPS 2022.
- Hülsing et al., "Post-quantum WireGuard", IEEE S&P 2021; Hashimoto et al., "Revisiting PQ WireGuard", IEEE S&P 2026.
- Companion paper: Noise XXhfs for libp2p *[TODO: title/link]*.
