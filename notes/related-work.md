# Related work: post-quantum key exchange on libp2p QUIC (Phase 0)

Compiled 2026-10-26. Every entry under "Verified sources" was opened (page, PDF text, datatracker,
or `gh`) during this review. Where only the abstract/landing page could be read, that is stated.
Entries under "Unverified leads" were seen only in search results or could not be loaded; do not
cite them until someone has opened them.

Question key used in "Does NOT cover":
- **Q1** census of libp2p implementations / mixed networks
- **Q2** cost (ClientHello ~1.5 KB, two Initial packets, latency under RTT/loss)
- **Q3** NAT hole punching (DCUtR over QUIC)
- **Q4** authentication (ML-DSA identities/certs, 3x anti-amplification, mutual auth with self-signed cert + identity extension)
- **Q5** downgrade (TLS 1.3 transcript binding vs Noise multistream-select gap)

---

## A. Standards and specifications

**A1. RFC 10024** — K. Kwiatkowski, P. Kampanakis, B. E. Westerbaan, D. Stebila, "Post-quantum hybrid
ECDHE-MLKEM Key Agreement for TLSv1.3", IETF Proposed Standard, August 2026 (formerly
draft-ietf-tls-ecdhe-mlkem).
URL: https://datatracker.ietf.org/doc/draft-ietf-tls-ecdhe-mlkem/
Confirmed: the datatracker shows the draft published as RFC 10024 (Proposed Standard); the IANA
entry for X25519MLKEM768 is codepoint 4588 (0x11EC), DTLS-OK, Recommended, referencing RFC 10024.
The -05 draft text gives the X25519MLKEM768 client share as 1216 bytes (1184 ML-KEM + 32 X25519) and
defines SecP256r1MLKEM768 and SecP384r1MLKEM1024 too.
Does NOT cover: Q1–Q5 empirically; it is the codepoint/encoding spec only.

**A2. RFC 9954** — D. Stebila, S. Fluhrer, S. Gueron, "Hybrid Key Exchange in TLS 1.3", IETF
Informational, July 2026 (was draft-ietf-tls-hybrid-design).
URL: https://datatracker.ietf.org/doc/rfc9954/
Framework: each hybrid combination is a single new named group negotiated by ordinary TLS 1.3
mechanisms; it does not pick algorithms. Relevant to Q5 because group negotiation therefore inherits
TLS 1.3's transcript protection.
Does NOT cover: QUIC, P2P, measurements (Q1–Q4).

**A3. RFC 9000** — J. Iyengar, M. Thomson (eds.), "QUIC: A UDP-Based Multiplexed and Secure
Transport", IETF, 2021.
URL: https://www.rfc-editor.org/rfc/rfc9000.html
Section 8.1 (verified): before address validation "servers MUST NOT send more than three times as
many bytes as the number of bytes they have received"; Section 8 states the limit for endpoints in
general. This is the constraint for Q4. (The 1200-byte Initial padding rule is in Section 14.1; that
text was not read in this pass — quote it from the RFC directly before citing.)
Does NOT cover: PQ sizes, P2P, hole punching.

**A4. RFC 9001** — M. Thomson, S. Turner (eds.), "Using TLS to Secure QUIC", IETF, 2021.
URL: https://www.rfc-editor.org/rfc/rfc9001.html
Section 4.3 "ClientHello Size" (verified): a typical ClientHello fits in a 1200-byte packet, but
multiple/large key shares can exceed it; if the ClientHello spans multiple Initial packets, servers
that need the whole ClientHello must buffer fragments, which is costly before address validation,
and they MAY use Retry to buffer only for validated clients. Directly relevant to Q2/Q3 (a Retry
or buffering stall during a simultaneous-open punch).
Does NOT cover: measurements; P2P; hole punching.

**A5. QUIC WG PR #3045** — D. Schinazi, "Allow ClientHello to span multiple QUIC packets",
quicwg/base-drafts, opened 17 Sep 2019, merged 31 Oct 2019.
URL: https://github.com/quicwg/base-drafts/pull/3045
Removed the single-datagram ClientHello requirement explicitly to unblock PQ experiments; debate
covered server buffering, attack surface and slow-loris; Retry offered as the mitigation. Useful
history for Q2.
Does NOT cover: any measurement; P2P (Q1, Q3, Q4, Q5).

**A6. draft-ietf-tls-mldsa-06** — T. Hollebeek, S. Schmieg, B. Westerbaan, "Use of ML-DSA in TLS 1.3",
IETF TLS WG, 11 Sep 2026; submitted to IESG, Informational, no RFC number yet.
URL: https://datatracker.ietf.org/doc/draft-ietf-tls-mldsa/
Defines ML-DSA-44/-65/-87 SignatureScheme codepoints for TLS 1.3. The datatracker page did not
list key/signature sizes (take those from FIPS 204).
Does NOT cover: QUIC amplification, self-signed P2P certs, performance (Q1–Q3, Q5).

**A7. draft-ietf-tls-key-share-prediction-05** — D. Benjamin, "TLS Key Share Prediction", IETF TLS WG,
15 Oct 2026, Standards Track draft (updates RFC 8446 if approved).
URL: https://datatracker.ietf.org/doc/draft-ietf-tls-key-share-prediction/
States the transition problem: guessing the wrong key share costs a HelloRetryRequest round trip,
and sending both PQ and classical shares costs bandwidth; proposes DNS SvcParam hints and discusses
downgrade (clients must send the full supported_groups list; servers should not pick classical over
PQ just because of key_share). Directly relevant to Q1 (mixed swarms) and Q5.
Does NOT cover: libp2p (no DNS SVCB for peers), QUIC Initial sizing, P2P.

**A8. libp2p TLS handshake spec** — libp2p/specs, `tls/tls.md`.
URL: https://github.com/libp2p/specs/blob/master/tls/tls.md
TLS 1.3 only; single self-signed certificate (chains rejected); host key signs
`libp2p-tls-handshake:` || SPKI in the extension OID 1.3.6.1.4.1.53594.1.1; ALPN `libp2p`; no SNI.
The spec names no key-exchange groups and does not mention PQ — so group choice is left to each
TLS stack's defaults (the basis of Q1).
Does NOT cover: anything PQ.

**A9. libp2p PQ trackers** (opened via `gh`, 2026-10-26):
- libp2p/specs PR #710 "RFC-0004: ML-DSA Key Support for libp2p Peer Identities" (dozyio, opened 2026-04-11, open). https://github.com/libp2p/specs/pull/710
- rust-libp2p #6462 "Implement Post-Quantum Identities (ML-DSA / RFC-0004)" (open). https://github.com/libp2p/rust-libp2p/issues/6462
- rust-libp2p #6236 "Post-Quantum Key Exchange" (Noise + Kyber768, open). https://github.com/libp2p/rust-libp2p/issues/6236
Relevant to Q4: PQ identities are proposed but not specified; nobody has analysed their size
against QUIC's amplification budget.
Does NOT cover: measurement of any kind.

## B. PQ / hybrid handshakes in QUIC (closest prior work)

**B1. Kempf et al. 2024** — M. Kempf, N. Gauder, B. Jaeger, J. Zirngibl, G. Carle, "A Quantum of
QUIC: Dissecting Cryptography with Post-Quantum Insights", IFIP Networking 2024. arXiv:2405.09264.
URL: https://arxiv.org/abs/2405.09264 (HTML full text read)
Measured LSQUIC and quiche linked against the OQS BoringSSL fork on bare metal (RTT < 0.1 ms, no
emulated loss), time-to-first-byte for a 1-byte object. Tested Kyber, BIKE, HQC (and P-curve
hybrids) and Dilithium, Falcon, SPHINCS+. Kyber/Dilithium/Falcon have low handshake impact; SPHINCS+
blows up (up to 92 server packets; LSQUIC fails above ~30 kB certs due to a 64-packet mini-connection
limit). Explicitly observes the 3x amplification limit and Retry adding a round trip.
Does NOT cover: realistic RTT/loss (Q2 partly), X25519MLKEM768 as finally standardised, mutual auth,
P2P, hole punching, mixed-version swarms (Q1, Q3, Q5).

**B2. Montenegro-Montes, Ríos-del-Pozo, Bonilla 2026** — "Comparative analysis of post-quantum
handshake performance in QUIC and TLS protocols", Computer Networks 275, 111957 (2026).
DOI 10.1016/j.comnet.2025.111957. URL: https://riuma.uma.es/entities/publication/ffd4e647-f515-4951-b576-3cc4d85a79f0/full
(abstract and record read; full PDF host unreachable during this review.)
Framework integrating PQ and hybrid KEMs into TLS-over-TCP and QUIC, evaluated under ideal and
realistic (lossy/delayed) networks. Hybrid KEMs have the highest latency and bandwidth overhead;
QUIC consistently reduces the PQ penalty relative to TLS, especially under loss.
Does NOT cover (per abstract): libp2p stacks, P2P, mutual auth, hole punching, mixed swarms (Q1,
Q3–Q5). Check the full text for whether it isolates the two-Initial ClientHello effect (Q2).

**B3. Nawrocki et al. 2022** — M. Nawrocki, P. Fotouhi Tehrani, R. Hiesgen, J. Mücke, T. C. Schmidt,
M. Wählisch, "On the Interplay between TLS Certificates and QUIC Performance", ACM CoNEXT 2022,
pp. 204–213. arXiv:2211.02421.
URL: https://arxiv.org/abs/2211.02421
Internet measurement of >1M domains (~272k QUIC services): ~35% of server certificate chains already
exceed the amplification limit (losing QUIC's 1-RTT benefit), and some servers exceed the 3x factor.
Classical certificates only, but it is the canonical citation for Q4's amplification argument.
Does NOT cover: PQ, self-signed single-cert P2P auth (libp2p chains are one cert), Q1–Q3, Q5.

**B4. Kampanakis, ETSI/IQC 2023 slides** — P. Kampanakis (AWS), "The effects of Dilithium on QUIC's
performance", ETSI/IQC Quantum Safe Cryptography Event, 14 Feb 2023.
URL: https://docbox.etsi.org/Workshop/2023/02_QUANTUMSAFECRYPTOGRAPHY/TECHNICALTRACK/MIGRATIONandPERFORMANCECHALLENGES/AMAZON_Kampanakis.pdf
(text extracted from the PDF.) Key shares grow to 1–2 KB with Kyber; authentication data to 17+ KB
with Dilithium; extra RTT from the ~4 KB amplification window and from the ~15 KB initial congestion
window; preliminary QUIC results at 60 ms RTT; options are inflating the client request or trimming
auth data (e.g. caching CA certs). Slides, not peer-reviewed.
Does NOT cover: client auth, P2P, hole punching, mixed swarms (Q1, Q3, Q5).

**B5. IETF QUIC WG mailing-list thread, Jan 2024** — P. Kampanakis, "RE: Amplification window, initial
congestion window, initial RTT and new post-quantum signature implications", quic@ietf.org,
8 Jan 2024.
URL: https://mailarchive.ietf.org/arch/msg/quic/peISmymLLbvgNMWqyQphmkdnRDA
Argues amplification is QUIC/DTLS-specific and cannot be fixed in TLS; quotes M. Thomson that raising
the 3x factor by 3–5x "seems unwise". Evidence that the WG has not changed the limit for PQ.
Does NOT cover: measurement; P2P (all of Q1–Q3, Q5).

**B6. Mallick, Kundu, Kompella 2026** — "Study of Post Quantum status of Widely Used Protocols",
arXiv:2603.28728 (preprint).
URL: https://arxiv.org/abs/2603.28728
Survey of nine protocols including QUIC; TLS and Signal lead in hybrid PQ key exchange deployment.
Does NOT cover: libp2p/P2P, new measurements (Q1–Q5).

## C. PQ TLS 1.3 performance (TCP), authentication and certificate size

**C1. Sikeridis, Kampanakis, Devetsikiotis 2020** — "Post-Quantum Authentication in TLS 1.3: A
Performance Study", NDSS 2020, DOI 10.14722/ndss.2020.24203; ePrint 2020/071.
URL: https://eprint.iacr.org/2020/071
Benchmarks NIST PQ signature candidates in TLS 1.3 under realistic network conditions and server
load; proposes mixing algorithms in one chain. Abstract does not mention QUIC.
Does NOT cover: QUIC amplification, P2P mutual auth, Q1–Q3, Q5.

**C2. Kampanakis, Childs-Klein 2024** — "The impact of data-heavy, post-quantum TLS 1.3 on the
Time-To-Last-Byte of real-world connections", MADweb 2024; ePrint 2024/176.
URL: https://eprint.iacr.org/2024/176
ML-KEM + ML-DSA slowdown on time-to-last-byte is smaller than on the handshake and shrinks with data
size (<5% on stable links); larger under loss/volatility. TLS over TCP only.
Does NOT cover: QUIC, P2P (Q1, Q3–Q5); Q2 only by analogy.

**C3. Schwabe, Stebila, Wiggers 2020 (KEMTLS)** — "Post-quantum TLS without handshake signatures",
ACM CCS 2020, DOI 10.1145/3372297.3423350; ePrint 2020/534.
URL: https://eprint.iacr.org/2020/534/
Replaces server handshake signatures with KEMs; < half the bandwidth of comparable PQ TLS 1.3 in the
size-optimised setting. Mutual auth appears only as a security sketch.
Does NOT cover: QUIC, libp2p identity extension, measurements in P2P (Q1–Q3, Q5). A design
alternative to mention for Q4.

**C4. Westerbaan 2021** — B. Westerbaan, "Sizing Up Post-Quantum Signatures", Cloudflare blog,
8 Nov 2021.
URL: https://blog.cloudflare.com/sizing-up-post-quantum-signatures/
Padded real handshakes with 1–59 dummy 1 kB certificates (964,499 live connections, 24 days):
failures bump near 10 kB and 30 kB; a wall near 40 kB matching the initial congestion window; ~17 kB
(Dilithium2-sized) gives ~20% median slowdown. Test server had no HTTP/3.
Does NOT cover: QUIC amplification, P2P (Q1–Q3, Q5).

**C5. Westerbaan 2024** — B. Westerbaan, "The state of the post-quantum Internet", Cloudflare blog,
5 Mar 2024.
URL: https://blog.cloudflare.com/pq-2024/
~2% of TLS 1.3 connections to Cloudflare used PQ key agreement at the time; large ClientHellos broke
some middleboxes/servers (0.34% in origin tests of the fast method); ML-DSA-44 would add ~17 kB to a
typical handshake. No QUIC-specific PQ measurement; no amplification discussion.
Does NOT cover: Q1, Q3–Q5 in a P2P setting.

**C6. Westerbaan, Valenta 2024** — "A look at the latest post-quantum signature standardization
candidates", Cloudflare blog, 7 Nov 2024.
URL: https://blog.cloudflare.com/another-look-at-pq-signatures/
QUIC traffic statistics: median non-resumed QUIC connection carries 7.8 kB server→client; median
compressed chain 3.2 kB; ML-DSA as a drop-in would more than double lifetime bytes for most QUIC
connections; ML-DSA adds ~14.7 kB per handshake. No amplification analysis.
Does NOT cover: client/mutual auth, P2P (Q1, Q3, Q5).

## D. Deployment, middleboxes and implementation behaviour

**D1. tldr.fail** — "TLS post-quantum TL;DR fail" (maintainers via github.com/dadrian/tldr.fail).
URL: https://tldr.fail/
Documents servers that assume a ClientHello arrives in one read and fail when PQ ClientHellos span
TCP segments. States QUIC is much less likely to hit this because it never assumed a single-packet
ClientHello, is newer, and usually has TCP fallback.
Does NOT cover: QUIC measurements; P2P (no TCP fallback assumption in libp2p QUIC-only dials);
Q1, Q3–Q5.

**D2. Google QUICHE commit "Chaos Protection v2"** — D. Schinazi, commit 54f2123, 3 Dec 2024.
URL: https://quiche.googlesource.com/quiche/+/54f21233321b7a5ef64386f2dc11156039ae32a4
Commit message: "the emergence of post-quantum cryptography has now caused the ClientHello to span
multiple packets." Primary evidence that Chrome's QUIC ClientHello is multi-packet in practice.
Does NOT cover: measurement; P2P (Q1, Q3–Q5).

**D3. Go 1.24 release notes** — The Go Authors, "Go 1.24 Release Notes", 2025.
URL: https://go.dev/doc/go1.24
crypto/tls enables X25519MLKEM768 by default when `Config.CurvePreferences` is nil; `GODEBUG
tlsmlkem=0` reverts, citing tldr.fail. Primary source for the go-libp2p/quic-go leg of Q1 (whether
quic-go passes nil CurvePreferences must be checked in code).
Does NOT cover: libp2p specifically.

**D4. Syncthing forum thread** — "Support for Quantum Resistant Key Exchange", Syncthing Community
Forum, 5 Aug 2025 (reply by maintainer J. Borg).
URL: https://forum.syncthing.net/t/support-for-quantum-resistant-key-exchange/24723
A P2P Go application (self-signed certs) did not negotiate X25519MLKEM768 despite building with Go
1.24; the maintainer attributed this to Syncthing targeting an older Go version while building with
a newer one, and said it would be enabled in a later release. (Our reading, not the thread's: Go's
GODEBUG defaults follow the go.mod version; confirm before stating.) A direct
analogue of the Q1 "built with a new toolchain but not enabled" failure mode. Anecdotal.
Does NOT cover: measurement, QUIC specifics, Q2–Q5.

**D5. Wickramasinghe, Li, Jha, Shaghaghi 2026** — "Mind the Gap: Policy vs Reality in Post-Quantum
TLS Deployment", accepted to ACM IMC 2026; arXiv:2607.29005.
URL: https://arxiv.org/abs/2607.29005 (HTML read)
>2 billion handshakes, 1M domains, 11 vantage points, three scans (Jul 2025–Mar 2026). Deployment
converges on X25519MLKEM768; on 328,290 domains offering both, median hybrid-minus-classical handshake
time is 0 ms, ~1.1–1.2 KB extra per handshake. Methodology is TLS over TCP only ("focus exclusively
on TLS as used for HTTPS"); no QUIC.
Does NOT cover: QUIC, P2P, auth, hole punching (Q1 for libp2p, Q2 over QUIC, Q3–Q5).

**D6. Dubey, Varshney 2026** — "Measurement Study of Post-Quantum Readiness of Internet: 2026",
arXiv:2606.16473 (preprint).
URL: https://arxiv.org/abs/2606.16473
32,011 domains: 49.3% support hybrid PQ key exchange; 0% use PQ/hybrid certificates. Abstract does
not say QUIC was scanned.
Does NOT cover: P2P, QUIC-specific behaviour (Q1–Q5 for libp2p).

## E. NAT traversal, hole punching and UDP-constrained PQ handshakes

**E1. Ford, Srisuresh, Kegel 2005** — "Peer-to-Peer Communication Across Network Address
Translators", USENIX ATC 2005; arXiv:cs/0603074.
URL: https://arxiv.org/abs/cs/0603074
Foundational description and measurement of UDP/TCP hole punching (~82% of NATs tested supported
UDP, ~64% TCP).
Does NOT cover: QUIC, PQ, handshake size (Q1, Q2, Q4, Q5; Q3 only as background).

**E2. Seemann, Inden, Vyzovitis 2022** — "Decentralized Hole Punching", DINPS 2022.
URL: https://research.protocol.ai/publications/decentralized-hole-punching/ (abstract read)
Describes libp2p's infrastructure-free hole punching (AutoNAT/relay/DCUtR analogues of STUN/TURN/ICE).
Does NOT cover: PQ or handshake-size effects (Q1, Q2, Q4, Q5; Q3 without PQ).

**E3. Trautwein, Ihle, Schubotz, Breitinger, Gipp 2026** — "Large-Scale Measurement of NAT Traversal
for the Decentralized Web: A Case Study of DCUtR in IPFS", ACM IMC 2026, DOI 10.1145/3777912.3809138;
arXiv:2604.12484. (An earlier version appeared as arXiv:2510.27500, "Challenging Tribal Knowledge —
Large Scale Measurement Campaign on Decentralized NAT Traversal", Trautwein, Ihle, Schubotz, Gipp.)
URLs: https://arxiv.org/abs/2604.12484 ; https://arxiv.org/abs/2510.27500
4.4M DCUtR attempts, 85k networks, 167 countries: ~70% ± 7.1% conditional success; TCP and QUIC
statistically indistinguishable; 97.6% of successes on the first attempt; RTT-based synchronisation.
No mention of handshake size, ClientHello or PQ. This is the baseline Q3 must compare against.
Does NOT cover: PQ, multi-packet Initials, auth (Q1, Q2, Q4, Q5; Q3 without PQ).

**E4. Rene (ProbeLab) 2026** — S. Rene, "Can libp2p punch through NATs?", ProbeLab blog, 3 Aug 2026.
URL: https://probelab.io/blog/can-libp2p-punch-through-nats/
DCUtR spec audit, go-/rust-libp2p testbed across RFC 4787 NAT types (100% interop on punchable NATs),
and a live classified campaign (port-restricted cone 82.9%; ~36% of DCUtR-advertising peers never get
a relay reservation). Notes timing sensitivity of simultaneous dials. No PQ, no handshake size.
Does NOT cover: PQ (Q1, Q2, Q4, Q5; Q3 without PQ). A ready-made testbed design to reuse.

**E5. Hülsing, Ning, Schwabe, Weber, Zimmermann 2021** — "Post-quantum WireGuard", IEEE S&P 2021;
ePrint 2020/379.
URL: https://eprint.iacr.org/2020/379
KEM-based PQ WireGuard with PQ authentication. (The single-UDP-packet design constraint is stated in
E6's abstract, not in this abstract.)
Does NOT cover: QUIC/TLS, NAT traversal measurement (Q1–Q5 directly).

**E6. Hashimoto, Katsumata, Niot, Wiggers 2026** — "Revisiting PQ WireGuard: A Comprehensive Security
Analysis With a New Design Using Reinforced KEMs", IEEE S&P 2026; ePrint 2025/1758.
URL: https://eprint.iacr.org/2025/1758
Abstract: WireGuard handshake messages must fit one ~1200-byte UDP packet; PQ-WireGuard met this with
Classic McEliece + modified Saber at a large server-memory cost. A UDP P2P-adjacent protocol that
chose to *avoid* multi-packet handshakes — useful contrast for Q2/Q3.
Does NOT cover: QUIC, libp2p, measurement of NAT behaviour.

## F. PQ Noise (already known; cite in the QUIC paper's background)

**F1. Renckens, Rønne, Großschädl, Ryan 2024** — "An Evaluation of Post-Quantum and Hybrid Noise
Protocol Variants on Mobile Devices", SecITC 2024, Springer, DOI 10.1007/978-3-031-87760-5_12.
URL: https://orbilu.uni.lu/handle/10993/63642 (metadata read via curl; TLS certificate error in fetcher)
PQNoise and hybrid patterns in Noise-C, emulated networks on laptop/ARM.
Does NOT cover: QUIC/TLS at all.

**F2. Ahmed, Gangopadhyay, Zhang 2026** — "NoisePQC++: A Unified NIST-Compliant PQC and Hybrid-PQC
Implementation of the Noise Protocol", arXiv:2608.00954.
URL: https://arxiv.org/abs/2608.00954
Does NOT cover: QUIC, libp2p (abstract mentions neither).

---

## Unverified leads (do not cite until opened)

- Raavi, Wuthier, Chandramouli, Zhou, Chang, "QUIC Protocol with Post-quantum Authentication", ISC 2022,
  LNCS 13640, pp. 84–91 — seen only in search results/DBLP snippets; par.nsf.gov refused connections and
  DBLP served a bot wall. Reportedly compares Dilithium/Falcon in QUIC vs TCP/TLS with packet drops
  (OQS-OpenSSL 1.1.1). Possibly relevant to Q2/Q4; check whether it covers client certificates.
- Raavi, Wuthier, Zhou, Chang, "Post-Quantum QUIC Protocol in Cloud Networking", EuCNC/6G Summit 2023,
  pp. 573–578 — search results only (NSF host unreachable).
- Sosnowski, Wiedner, Hauser, Steger, Schoinianakis, Gallenmüller, Carle, "The Performance of
  Post-Quantum TLS 1.3", CoNEXT Companion 2023, DOI 10.1145/3624354.3630585 — TUM portal DNS failed;
  search snippet only. Emulated loss/bandwidth/delay; TLS over TCP. Likely relevant to Q2 baseline.
- Kampanakis, Kallitsis, "Faster post-quantum TLS handshakes without intermediate CA certificates",
  CSCML 2022 — amazon.science DNS failed. Cited as [CSCML22] in B4; argues PQ cert size issue in
  (D)TLS and QUIC. Not applicable to libp2p's single self-signed cert, but cite for Q4 context.
- Nawrocki et al., IETF 116 QUIC WG slides on handshake questions — PDF downloaded but text not
  extractable. https://datatracker.ietf.org/meeting/116/materials/slides-116-quic-revisiting-quic-handshakes-and-tls-deployment-about-three-challenges-00.pdf
- Google Security Blog, "A new path for Kyber on the web", 13 Sep 2024 — only header loaded.
  Chromium Blog "Protecting Chrome Traffic with Hybrid Kyber KEM" (Aug 2023) — mirrors only.
- Cloudflare Radar changelog 2026-05-29 on "Split ClientHello" bug detection — search snippet only.
- Self-published "nginx QUIC Initial crypto deadlock" blog (dnsdoh.art): claims a PQ ServerHello split
  over two Initial packets hangs nginx on loss (nginx#1616/#1617) — unverified, single source; if true
  it is directly relevant to Q2 loss behaviour and worth reproducing.
- Red Sift blogs (German) on ML-KEM ClientHello size and PQ signature sizes — vendor blogs, not opened.
- ePrint 2022/1556, "Intermediate Certificate Suppression in Post-Quantum TLS: An Approximate Membership
  Querying Approach" — not opened.
- rustls default key-exchange groups: docs.rs page lists X25519MLKEM768 but not which groups are default;
  confirm in rustls source/CHANGELOG for Q1.

---

## Novelty assessment

**Q1 Census / mixed networks — not found.** No study measures which libp2p (or any P2P) QUIC stacks
negotiate X25519MLKEM768. Internet-wide PQ adoption studies (D5, D6) scan HTTPS servers, and D5 is
explicitly TCP-only. Only adjacent evidence: toolchain defaults (D3), a P2P app silently not enabling
it (D4), and the standards discussion of key-share misprediction/HRR in mixed populations (A7). libp2p's
TLS spec leaves groups unspecified (A8). Claim is defensible, phrased as "first census for libp2p".

**Q2 Cost — partly covered.** PQ/hybrid QUIC handshake cost is measured by B1 (no emulated RTT/loss),
B2 (loss and delay; hybrid KEMs costliest; QUIC softens the penalty) and TLS-over-TCP baselines (C2,
D5). Multi-packet ClientHello is documented as real (A4, A5, D2) but no verified source quantifies the
two-Initial-packet effect under loss, nor with go/rust/py/nim libp2p stacks. Frame the contribution as
"the multi-Initial ClientHello under loss, on P2P stacks", and cite B1/B2 prominently.

**Q3 Hole punching — not found.** DCUtR is well measured without PQ (E3, E4) and timing-sensitive
(E3, E4); RFC 9001 notes multi-packet ClientHello buffering/Retry (A4); WireGuard avoided multi-packet
handshakes entirely (E6). Nothing verified connects PQ ClientHello size to hole-punch success or
timing. This is the strongest novelty claim; E3/E4 give the baseline and testbed design.

**Q4 Authentication / amplification — partly covered.** The PQ-certificate-versus-3x-limit problem is
well established for server-authenticated WebPKI chains (B1, B3, B4, B5, C4, C6; KEMTLS C3 as an
alternative). Not found: mutual auth with a single self-signed certificate plus a libp2p identity
extension, where the *client* also sends a large Certificate/CertificateVerify, nor analysis of ML-DSA
peer identities (A9 shows only proposals). Novelty is in the P2P mutual-auth case; do not claim the
amplification observation itself.

**Q5 Downgrade — partly covered (standards-level only).** That TLS 1.3 negotiates hybrid groups as
ordinary named groups (A2) and the downgrade considerations of key-share prediction (A7) are documented;
RFC 8446's transcript binding is standard knowledge (cite RFC 8446 directly after checking the exact
section). No verified work compares this with the libp2p Noise multistream-select downgrade gap. The
comparison is new but small; present it as an analysis, not a headline result.
