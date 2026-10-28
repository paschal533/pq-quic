# RQ4: authentication and amplification (draft, 2026-10-28)

Status: desk analysis plus offline decoding of traces we already had. No new network runs.
Measured numbers cite claim IDs or data paths. Computed numbers show their arithmetic.
Anything not checked is marked **UNVERIFIED**.

## (a) Which key must be ML-DSA

In libp2p TLS, authentication is a chain of two signatures (spec `tls/tls.md` @ f201689524, lines 58–93):

1. **Identity → cert key.** The host (identity) key signs `"libp2p-tls-handshake:" || SPKI(cert key)`, carried in extension 1.3.6.1.4.1.53594.1.1.
2. **Cert key → this handshake.** The cert key signs the TLS 1.3 transcript (CertificateVerify).

There is also the X.509 self-signature by the cert key. The spec requires it to be valid (line 64), but it adds no authentication: whoever holds the cert key can produce it.

An attacker with a quantum computer can impersonate peer P by breaking either link:

- **Classical identity key (Ed25519 today):** recover P's private key from its public key. The attacker needs no handshake for this, because an Ed25519 peer ID is an identity multihash that contains the public key. The attacker then mints its own cert, signs the extension as P, and is P everywhere, permanently. An ML-DSA cert key does not help.
- **PQ identity key, classical cert key:** dial P and receive P's legitimate cert. Recover the ECDSA P-256 cert private key, then present P's cert to a victim and sign CertificateVerify with it. **One forged signature (CertificateVerify) is enough.** This is easy in practice because both stacks reuse one cert for the life of the transport:
  - go-libp2p v0.51.0 builds the cert once in `NewIdentity` (`p2p/security/tls/crypto.go:71-94`) with `certValidityPeriod` ≈ 100 years (`:25`).
  - rust libp2p-quic 0.14.0 builds the client and server configs once (`src/config.rs:81-85`, which calls `libp2p_tls::make_{client,server}_config`, and those call `certificate::generate`).

  So the cert key can be broken offline, not during the handshake. The spec allows reuse ("MAY reuse the same key and certificate", line 60).

  If the cert key were fresh for every connection, the attacker would have to break it within the handshake timeout. That is a harder threat model, but it is still a break.

**Answer: both keys.** The identity key matters more, because its break is permanent and needs no interaction. A PQ identity with a classical cert key buys nothing against an active quantum attacker.

Because the spec demands a valid self-signature, an ML-DSA cert key also pays for an ML-DSA self-signature (+2.4–4.6 KB) that carries no security weight. Dropping that check is a possible spec optimisation (idea only, not evaluated).

Unlike key exchange, authentication has no harvest-now-decrypt-later exposure. It only has to be PQ before a quantum computer exists. The migration problem is that peer IDs are long-lived.

## (b) Sizes

**FIPS 204 Table 2** (local `PQC-Research/materials/nist.fips.204.final.pdf`, Table 2, printed p.16):

| | public key | signature |
|---|---:|---:|
| ML-DSA-44 | 1,312 | 2,420 |
| ML-DSA-65 | 1,952 | 3,309 |
| ML-DSA-87 | 2,592 | 4,627 |

The same constants appear in Go 1.27.0 `api/go1.27.txt:mldsa` and in specs PR #710's table.

**Measured today.** These come from decrypting Handshake space in `data/bench/randomloss-20261026T215115Z/{go,rust}-loss0.02.{jsonl,keys}` with the scratchpad script `flight_sizes.py`, which reuses `harness/tap/handshake_space.py`. Clients 0–4 were decoded. Sizes are TLS message bytes including the 4-B header.

| server flight message | go-libp2p v0.51.0 | rust-libp2p 0.57.1 |
|---|---:|---:|
| ServerHello (classical / hybrid) | 90 / 1,178 | 90 / 1,178 |
| EncryptedExtensions | 130–142 | 142–154 |
| CertificateRequest | 65 | 31 |
| Certificate (cert DER) | 447 (434) | 403 (390) |
| of which libp2p extension | 122 (not critical) | 125 (critical, `01 01 ff`) |
| CertificateVerify | 79 (ecdsa_secp256r1_sha256, 71-B sig) | 79 |
| Finished | 36 | 36 |
| Handshake-space total (excl. SH) | 757–769 | 691–703 |

- **Key types:** the cert key is ECDSA P-256 (ecPublicKey OID present; go `crypto.go:243`, rust `certificate.rs:45`). The identity key is Ed25519 (protobuf `08 01 12 20` + 32 B, 64-B signature).
- **Client flight:** Certificate 447–450 (go) / 404–405 (rust), plus CertificateVerify 78–80 and Finished 36.

**Projected sizes, using the go server as the base.** All DER lengths are under 64 KiB, so every large header is 4 B (`30 82 xx xx`).

- **Cert key P-256 → ML-DSA:**
  - SPKI: 91 → 4+13+(4+1+pk) = **1,334 / 1,974 / 2,614** (Δ +1,243 / +1,883 / +2,523). The AlgorithmIdentifier is 13 B (11-B OID, no params), per RFC 9881. **UNVERIFIED: the RFC 9881 encoding was not re-read.**
  - signatureAlgorithm, which appears twice: 12 → 13 B each (Δ +2).
  - Self-signature BIT STRING: ~74 → 4+1+sig = **2,425 / 3,314 / 4,632** (Δ +2,351 / +3,240 / +4,558).
- **Identity Ed25519 → ML-DSA**, in specs #710 encoding: Data = 1-B variant + pk, KeyType 4.
  - Protobuf = 2 + 1 + 2 (varint) + (1+pk).
  - SignedKey = SEQ{OCTET(pb), OCTET(sig)}, wrapped in an extnValue OCTET and the Extension SEQ (12-B OID, no critical flag).
  - ML-DSA-44: pb 1,318 → OCTET 1,322; sig OCTET 2,424; SEQ 4+3,746 = 3,750; extnValue 3,754; extension 4+12+3,754 = **3,770** (Δ +3,648).
  - ML-DSA-65: pb 1,958 → 1,962; sig 3,313; SEQ 5,279; extnValue 5,283; extension **5,299** (Δ +5,177).
  - ML-DSA-87: pb 2,598 → 2,602; sig 4,631; SEQ 7,237; extnValue 7,241; extension **7,257** (Δ +7,135).
  - The PKIX encoding (specs #711) would differ by tens of bytes. UNVERIFIED.
- **Extensions wrapper** (`a3 7c 30 7a` → `a3 82.. 30 82..`): +4.

Totals, with Certificate msg = DER + 13 and CertificateVerify msg = 8 + sig:

| config (identity / cert key) | cert DER | Certificate msg | CertificateVerify msg |
|---|---:|---:|---:|
| A Ed25519 / P-256 (measured) | 434 | 447 | 79 |
| B ML-DSA-44 / P-256 (insecure, see a) | 434+3,648+4 = 4,086 | 4,099 | 79 |
| C ML-DSA-44 / ML-DSA-44 | 434+1,243+2+2,351+3,648+4 = 7,682 | 7,695 | 2,428 |
| D ML-DSA-65 / ML-DSA-65 | 434+1,883+2+3,240+5,177+4 = 10,740 | 10,753 | 3,317 |
| E ML-DSA-87 / ML-DSA-87 | 434+2,523+2+4,558+7,135+4 = 14,656 | 14,669 | 4,635 |

The client sends the same Certificate and CertificateVerify, because client authentication is mandatory.

## (c) Server first flight vs the 3× budget

**Measured wire bytes.** These are server UDP payload bytes sent before the client's first Handshake packet, from `data/bench/targeted-20261026T173953Z/*-dropnone.jsonl` (n = 30–31 per variant) and the scratchpad script `wire_flight.py`.

| server | classical CH | hybrid CH |
|---|---|---|
| go | client 1 dgram / 1,280 B; server 1 dgram, **1,280 B** | client 2 / 2,560; server 2 dgrams, **2,166–2,191 B** (1,280 Initial + ~900) |
| rust | client 1 / 1,200; server **1,338 B** (1,200 + 138 short-header) | client 2–3 / 2,400–3,600; server **2,538 B** (1,200 + 1,200 + 138, SH split as in C-28) |

**Measured overhead per packet.** A go Handshake packet of 805 B carried 765 TLS bytes, so about 40 B of overhead (header up to the packet number is 17 B with 4-B CIDs, plus the 16-B AEAD tag and CRYPTO framing). rust's header to the packet number is 25 B (8-B CIDs), so its overhead is about 47 B. This was checked on one client each.

**Projection** (go server, 1,280-B datagrams). Wire ≈ TLS bytes + 40 B × ⌈HS/1,240⌉ datagrams. For a hybrid CH, add a separate 1,280-B Initial datagram for the SH.

- Handshake-space TLS bytes = 239 (EE 138 + CR 65 + Fin 36) + Certificate + CertificateVerify:
  - A: 765
  - B: 4,417
  - C: 10,362
  - D: 14,309
  - E: 19,543
- Budget = 3 × client bytes received:
  - go: classical 3 × 1,280 = **3,840**; hybrid 3 × 2,560 = **7,680**
  - rust: 3,600 / 7,200

| config | flight vs classical CH | fits 3,840? | flight vs hybrid CH | fits 7,680? | amplification-limited extra RTT (classical / hybrid CH) |
|---|---|---|---|---|---|
| A | 1,280 (measured) | yes (33%) | ~2,180 (measured) | yes (28%) | 0 / 0 |
| B | 90+4,417+4×40 ≈ 4,670 | **no** | 1,280+4,417+4×40 ≈ 5,860 | **yes** | **1 / 0** |
| C | 90+10,362+9×40 ≈ 10,810 | no | 1,280+10,362+9×40 ≈ 12,000 | no | 1 / 1 |
| D | 90+14,309+12×40 ≈ 14,880 | no | 1,280+14,309+12×40 ≈ 16,070 | no | 1 / 1 |
| E | 90+19,543+16×40 ≈ 20,270 | no | 1,280+19,543+16×40 ≈ 21,460 | no | 1 / 1 (≥1 on quinn, see below) |

rust server flights are about 60–75 B smaller (measured), and its budgets are 3,600 / 7,200. No verdict changes.

**Why at most one extra RTT (reasoning).** The SH always fits in the first budget, so the client gets Handshake keys from the first server datagram. Its reply (an Initial ACK and a Handshake ACK) adds 3× more budget, and the Handshake packet validates the client's address, which lifts the limit altogether. The rest of the flight therefore leaves one RTT later. RFC 9000 §8.1, checked against rfc-editor.org on 2026-10-28: "Prior to validating the client address, servers MUST NOT send more than three times as many bytes as the number of bytes they have received", and "Once an endpoint has successfully processed a Handshake packet from the peer, it can consider the peer address to have been validated." **UNVERIFIED** (not re-read): §14.1 requires client Initial datagrams of at least 1,200 B; §13.2.1 requires immediate ACK of Initial and Handshake packets.

**Interesting effect.** The hybrid ClientHello's second datagram doubles the server's pre-validation budget (3,840 → 7,680 for go). That is enough to carry config B in one flight where a classical CH cannot. The hybrid ClientHello is therefore *partly self-financing*: PQ key exchange buys room for PQ authentication. That room runs out at C, since 12,000 > 7,680. A matching test: pad classical Initials to 2 datagrams. UNVERIFIED, not run.

**Congestion window as a second limit.** quinn-proto 0.11.19 initial window = `14720.clamp(2*1200, 10*1200)` = **12,000 B** (`src/congestion/cubic.rs:266`, `new_reno.rs:162`, `BASE_DATAGRAM_SIZE = 1200` at `congestion.rs:105`). The doc comment quotes RFC 9002's `min(10*mds, max(2*mds, 14720))`.

Configs D and E (14.9–21.5 KB) exceed 12,000 even with no amplification limit. After the first ACK, slow start should allow the rest. For E with a classical CH on quinn, however: 3,600 B are sent first, leaving ~16.7 KB, against a window of ≈ 12,000 + 3,600 = 15,600. That would need a third flight, so **+2 RTT is plausible (estimate, UNVERIFIED)**. The quic-go initial window was not checked (**UNVERIFIED**).

The client's own Certificate and CertificateVerify (up to ~19 KB for E) go out after address validation, so they are not amplification-limited. They are still subject to the client's congestion window.

## (d) Who can do ML-DSA in TLS today

- **On the wire (measured): no libp2p stack offers ML-DSA.**
  - go v0.51.0 / Go 1.26.10: rsa_pss×3, ecdsa p256/384/521, ed25519 (`data/go-go.jsonl`).
  - rust 0.57.1 and js 3.5.1: 9 schemes, ecdsa/ed25519/rsa only (`data/rust-rust.jsonl`, `data/js-js.jsonl`).
  - nim: ed25519 and ecdsa_p256 only (C-24).
  - Chrome 155: no ML-DSA (`data/chrome-to-go-wt.jsonl`).
- **Go:**
  - The public `crypto/mldsa` package and the `crypto/tls` constants `MLDSA44/65/87` (0x0904–0x0906) are new in **Go 1.27**. They are listed in `api/go1.27.txt` (#77626, #78888), so Go 1.26 lacks them. That matches #710's note "no public API as of Go 1.26". **Go 1.27 is released** (go.dev/dl lists go1.27.3 as current stable on 2026-10-28; `crypto/mldsa` constants confirmed in golang/go master `api/go1.27.txt`). Our census and timing peers were built with Go 1.26.10, one major version behind.
  - In Go 1.27.0, ML-DSA is first in `defaultSupportedSignatureAlgorithms` (`crypto/tls/defaults.go:51-53`), and x509 parses ML-DSA (`x509.MLDSA`).
  - go-libp2p v0.51.0 still hard-codes the cert key `ecdsa.GenerateKey(elliptic.P256())` (`crypto.go:243`), and core/crypto KeyType has no ML-DSA (`core/crypto/pb/crypto.pb.go:27-30`).
- **rustls 0.23.46 + aws-lc-rs 1.18.2** (our Cargo.lock): has `ML_DSA_44/65/87` (`enums.rs:518-520`), verification (`crypto/aws_lc_rs/mod.rs:180-182, 235-237`) and signing (`sign.rs:427-437`).
  - libp2p-tls 0.7.0 blocks it in two places: `verification_schemes()` lists no ML-DSA (`verifier.rs:88-103`), and verification goes through `ring` with a hard-coded match (`certificate.rs:320-360`). Both are code changes in libp2p-tls, not rustls. rustls-post-quantum: not checked, **UNVERIFIED**.
- **BoringSSL** (vendored in nim-boringssl 0.0.14): has `SSL_SIGN_ML_DSA_44/65/87` (`include/openssl/ssl.h:1239-1241`), and ML-DSA is first in the default *signing* list (`ssl/extensions.cc:308-310`). It is absent from the default *verify* list (`extensions.cc:286-302`), so a peer must opt in. nim-libp2p sets its own list anyway (C-24). The BoringSSL commit inside nim-boringssl is UNVERIFIED. lsquic needs nothing extra beyond BoringSSL, by reasoning (**UNVERIFIED**).
- **js:**
  - @chainsafe/libp2p-quic offers the same 9 schemes as rust (measured). That it wraps libp2p-tls is **UNVERIFIED**.
  - js-libp2p's TCP TLS encrypter makes ECDSA P-256 cert keys via WebCrypto (`packages/connection-encrypter-tls/src/utils.ts:100-105`, local clone 2a3e54738).
  - Node and browser ML-DSA support: per #3432, Node is experimental and browsers lack it.

## (e) js-libp2p #3432 and specs discussion

- **#3432** is a *draft PR*, not an issue, by dozyio (opened 2026-04-03, still open): "feat: Post quantum identities with ML-DSA". It reads "Experimental support for ML-DSA-44, ML-DSA-65 & ML-DSA-87 keys". Its open questions: "Need to decide on default scheme", "Need to decide if dual sig is required".
  - It touches `crypto`, `peer-id` and the `connection-encrypter-tls` KeyType proto. That is the **identity key only**. Per (a), the TLS cert key stays P-256 (`utils.ts:100`), so #3432 alone gives config B: bigger, but not quantum-safe against an active attacker.
  - Benchmarks are in the PR body (node-subtle ML-DSA-65 sign ≈ 1,699 ops/s).
- **specs #710** (RFC-0004, open): KeyType `MLDSA = 4` and a 1-B variant prefix. Peer IDs always use SHA-256 multihash, because the key is over 42 B. Its Security Considerations say it "does not by itself provide hybrid authentication or downgrade resistance". It says nothing about the TLS cert key.
- **specs #711** (MarcoPolo, PKIX/PKCS#8 keys, which reuses RFC 9881) is offered as an alternative to #710. #712 covers COSE keys, and #717 is a "docs: pkix" follow-up. A 2026-06-05 comment on #3432 asks to align with "PKIX PR" and says py, dotnet and c libp2p will follow.
- **specs #709** (identify message sizes) matters for large keys. Not read in detail.
- **Gap for the paper:** no libp2p spec or PR found that addresses the **TLS cert key** or amplification. Searched "quantum", "ML-DSA" and "mldsa" across libp2p/specs PRs and issues.

## Sources

- FIPS 204 (Aug 2024), Table 2: `PQC-Research/materials/nist.fips.204.final.pdf`
- libp2p TLS spec `tls/tls.md` @ f201689524 (2025-05-16)
- Our data: C-01, C-02, C-13, C-14, C-15, C-24, C-28; `data/bench/randomloss-20261026T215115Z/*.keys/jsonl`; `data/bench/targeted-20261026T173953Z/*-dropnone.jsonl`; offline scripts in the session scratchpad (`flight_sizes.py`, `wire_flight.py`, built on `harness/tap/`)
- go-libp2p v0.51.0 `p2p/security/tls/crypto.go:25,71-94,243`; Go 1.27.0 `api/go1.27.txt`, `crypto/tls/common.go:433-435`, `defaults.go:51-53`
- libp2p-tls 0.7.0 (`harness/rust-pair/vendor/libp2p-tls`) `certificate.rs:45,102,320-360`, `verifier.rs:88-103`; libp2p-quic 0.14.0 `config.rs:81-85`; rustls 0.23.46; quinn-proto 0.11.19 `congestion/cubic.rs:266`, `congestion.rs:105`
- BoringSSL in nim-boringssl 0.0.14: `ssl.h:1239-1241`, `ssl/extensions.cc:286-310`, `ssl/ssl_privkey.cc:111-117`
- js-libp2p PR #3432; libp2p/specs PRs #709, #710 (RFC-0004 @ a917466), #711, #712, #717 (via `gh`, 2026-10-27)
- RFC 9000 §8.1 (3× limit, Handshake packet validates; wording checked 2026-10-28), §13.2.1, §14.1; RFC 9002 §7.2; RFC 9881 (these four not re-read).
