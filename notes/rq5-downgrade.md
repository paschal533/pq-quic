# RQ5 — downgrade resistance of libp2p over QUIC (2026-10-27)

Research question: can an on-path attacker strip the hybrid key exchange from a
libp2p-QUIC handshake and force a classical (harvest-now-decrypt-later) session,
the way the companion Noise paper shows is possible in multistream-select?

Short answer: **no, not without detection.** Over QUIC the key-exchange
negotiation *is* the TLS 1.3 ClientHello, and the ClientHello is bound into the
TLS transcript. Any on-path edit is readable and writable (Initial packets are
only obfuscated, not secret) but is caught cryptographically at the Finished.
The one thing that would turn detection into a real downgrade — a stack that
retries classical-only after a failure — does not exist in go-libp2p,
rust-libp2p, or js-libp2p (checked below). This is the structural opposite of the
Noise finding, where negotiation sits *outside* the handshake transcript.

Everything below is either an RFC section, a source line, or an artefact in this
repo. Unverified items are collected at the end.

## 1. What an on-path attacker can and cannot touch

QUIC v1 Initial packets are protected with AEAD keys derived from the client's
original Destination Connection ID and a fixed salt (RFC 9001 §5.2, `initial_salt`
`0x38762cf7…`), so **any observer can decrypt, modify, and re-encrypt them** — the
DCID is on the wire. This is verified here: `harness/tap/decode_initial.py` derives
those keys and its `--self-test` checks them against RFC 9001 Appendix A.1, and the
new `harness/tap/downgrade_proxy.py` re-encrypts them (test
`test_encrypt_is_inverse_of_decrypt` round-trips 5 real client Initials from
`data/go-go.jsonl`). So "packet protection" is **not** the defence here — the
ClientHello is in cleartext-to-anyone CRYPTO frames (RFC 9000 §19.6) inside the
Initial packets.

The defence is the TLS 1.3 **transcript**.

## 2. What TLS 1.3 binds (and how the transcript catches edits)

The negotiation fields the attacker would want to edit are all inside the
ClientHello and therefore inside the transcript:

| Field | Extension | RFC 8446 |
|---|---|---|
| Offered groups (e.g. `X25519MLKEM768` 0x11EC + `X25519` 0x1D) | `supported_groups` | §4.2.7 |
| Sent shares (hybrid 1216 B + X25519 32 B) | `key_share` (`KeyShareEntry`) | §4.2.8 |
| Server's forced re-offer | `HelloRetryRequest` | §4.1.4 |

**Transcript hash (RFC 8446 §4.4.1).** The transcript is the concatenation of the
handshake messages *as each party saw them*. The client hashes the ClientHello it
**sent** (with 0x11EC); a tampering server hashes the ClientHello it **received**
(stripped). For a HelloRetryRequest exchange, §4.4.1 replaces ClientHello1 in the
transcript with a synthetic `message_hash` message carrying `Hash(ClientHello1)` —
so even the pre-HRR ClientHello is bound, and an attacker cannot hide an edit by
forcing an HRR.

**Why an edit is fatal (RFC 8446 §7.1, §4.4.3, §4.4.4).** Handshake traffic secrets
are `Derive-Secret(Handshake Secret, "c hs traffic"/"s hs traffic",
ClientHello…ServerHello)` — the transcript hash is an input. Even if the attacker
leaves the X25519 share untouched so both sides compute the *same* ECDHE Handshake
Secret, the two sides feed **different** transcript hashes into Derive-Secret, so
they derive **different** handshake keys. The honest client then cannot even AEAD-
decrypt the server's EncryptedExtensions/Finished, and `CertificateVerify` (§4.4.3,
a signature over the transcript hash) and `Finished` (§4.4.4, an HMAC over the
transcript hash) cannot verify. The handshake aborts. The attacker cannot repair
this: it has neither private key, so it cannot recompute the keys, re-sign
CertificateVerify, or forge Finished.

**Downgrade sentinels are not the mechanism here (checked).** RFC 8446 §4.1.3 puts
`DOWNGRD\x01`/`\x00` in the last 8 bytes of `ServerHello.random` when a TLS 1.3
server negotiates TLS **1.2 or below**. That protects *version* downgrade, not a
within-1.3 group downgrade, and libp2p pins TLS 1.3 anyway (§4 below), so the
sentinel is not what defeats this attack — the transcript binding is.

**QUIC adds ALPN authentication.** RFC 9001 §8.1 requires the handshake to carry
authenticated ALPN; the value is in the (transcript-bound) ClientHello and echoed in
the server's EncryptedExtensions. libp2p-QUIC fixes ALPN to the single string
`"libp2p"` and runs **no multistream-select before the security handshake** —
contrast §5.

## 3. Detectable vs. not

| Attacker action | Detected? | Why |
|---|---|---|
| Edit any ClientHello byte (strip 0x11EC from `supported_groups`/`key_share`, flip order, force HRR) | **Yes** | transcript mismatch → handshake keys differ → Finished/CertVerify fail (§2) |
| Drop / delay Initial packets | Not "detected", but no downgrade | QUIC loss recovery just retransmits the *same* ClientHello (RFC 9002); it never rewrites it. Cost only — that is RQ2, claims C-18/C-19. |
| **Force a classical retry** (the only real downgrade path) | **Does not exist** | no stack retries with a classical-only ClientHello after failure — §4 |

The attack therefore only succeeds if some stack, after the hybrid handshake
fails, **re-dials offering classical-only**. That is the thing to rule out.

## 4. No classical-retry path in any stack (source-checked)

The TLS crypto config (the named groups offered) is built **once** per transport
from a fixed provider, with no attacker-influenced input and no per-attempt or
on-failure variation. A dial-level retry (swarm/host) re-runs the *same* transport
and thus re-sends an **identical** ClientHello.

**rust-libp2p 0.57.1** (libp2p-tls 0.7.0, libp2p-quic 0.14.0, quinn-proto 0.11.19,
rustls 0.23.46; vendored under `harness/rust-pair/vendor/`):
- `make_client_config` builds one `rustls::ClientConfig` from
  `aws_lc_rs::default_provider()` — `vendor/libp2p-tls/src/lib.rs:49-78`. The hybrid-
  first ordering is the provider default; the in-crate test `prefers_x25519_mlkem768`
  asserts `kx_groups[0] == X25519MLKEM768` (`lib.rs:112-118`).
- TLS is pinned to 1.3 only: `PROTOCOL_VERSIONS = &[&rustls::version::TLS13]`
  (`vendor/libp2p-tls/src/verifier.rs:48`); `verify_tls12_signature` is
  `unreachable!` (`verifier.rs:133-140`). So version downgrade is impossible.
- ALPN fixed: `const P2P_ALPN: [u8;6] = *b"libp2p"` (`lib.rs:39`), set at `lib.rs:73`.
- `grep -niE 'retry|fallback|reconnect|redial|classical' vendor/libp2p-quic/src/` →
  **no matches**. The only group-changing branch anywhere is the harness-only patch
  `PQQUIC_CLASSICAL=1` (`lib.rs:43-46`), an env var set by *us* for baselines
  (claim C-13), not reachable by a network attacker.
- quinn-proto 0.11.19 (`~/.cargo/registry/.../quinn-proto-0.11.19/src/`):
  `grep -niE 'downgrade|fallback|tls12'` → **no matches**.

**go-libp2p 0.51.0** (quic-go 0.64.1; source at
`C:\Users\user\Documents\go-libp2p`, quic-go vendored at
`harness/go-pair/vendor-quic-go`):
- QUIC ALPN hardcoded: `tlsConf.NextProtos = []string{"libp2p"}`
  (`p2p/transport/quic/transport.go:295`).
- TLS 1.3 floor: `MinVersion: tls.VersionTLS13` (`p2p/security/tls/crypto.go:91`).
- No `CurvePreferences`/`CurveID`/`fallback`/`downgrade`/`retry` override in
  `p2p/transport/quic` or `p2p/security/tls` (grep empty); the offered groups are
  Go's crypto/tls defaults, which include X25519MLKEM768 since Go 1.24 and are turned
  off only by `GODEBUG=tlsmlkem=0` — a process env, not an on-wire signal
  (`harness/go-pair/main.go:8`, claim C-13).

**js-libp2p** (`@chainsafe/libp2p-quic` 2.1.5): a native binding over the **same
quinn/rustls (aws-lc-rs) stack** as rust-libp2p; the census shows identical behaviour
(offers 0x11EC + X25519, selects the hybrid, claim C-14). The retry argument is the
rust one. *Not separately line-cited* — the shipped module is a minified native addon;
see Unverified.

Corollary: the aioquic path shows the *honest* no-share outcome is a hard failure,
not a silent classical fallback — restricting the server to a group the client did not
share yields `CONNECTION_CLOSE 0x128 "No supported key share"`, no HRR, no downgrade
(claim C-08).

## 5. Contrast with the Noise paper

The companion Noise paper's downgrade result exists precisely because libp2p's
**security negotiation runs in multistream-select, which is outside the Noise
handshake transcript** (`PQC-Research/paper-v2-draft.md`; audit
`PQC-Research/career/applications-2026q4/audit-paper1-noise.md` L112-116, L21). An
attacker can rewrite the `/noise`-vs-hybrid protocol-id line before the handshake
that would authenticate it; the paper's fix is a **classical-path transcript
binding** that folds the negotiated id into the handshake, with an 89-byte cross-
language strip-and-refuse demo (artifacts `3675d88`).

Over QUIC that gap is closed by construction:
- There is **no multistream-select before security** — ALPN is the single fixed
  string `"libp2p"` (§4), carried inside the TLS ClientHello, which is itself
  transcript-bound (RFC 9001 §8.1; RFC 8446 §4.2 extensions are covered by §4.4.1).
- So the negotiation an attacker would target is already *inside* the authenticated
  transcript, with no separate unauthenticated pre-handshake step to rewrite.

The paper's one-line framing: **in Noise the downgrade lever is outside the
transcript and needed a new binding; over QUIC/TLS 1.3 the same lever is already
inside the transcript, so the same strip attack is self-defeating.**

## 6. The attacker tool

`harness/tap/downgrade_proxy.py` (modelled on `harness/tap/quic_tap.py`, reusing the
RFC-9001-checked key schedule and parsing from `decode_initial.py`).

- `--mode strip`: deletes the `X25519MLKEM768` (0x11EC) entry from `supported_groups`
  and its `KeyShareEntry` from `key_share`, leaving the X25519 share. A tolerant server
  then selects X25519 **but** the honest client's transcript still holds the hybrid, so
  Finished fails.
- `--mode hrr-force`: deletes **every** hybrid/PQ group (0x11EB/0x11EC/0x11ED, the
  ML-KEM-only 0x0200–0x0202, and the Kyber draft 0x6399) from `supported_groups` **and**
  empties the `client_shares` vector (legal per RFC 8446 §4.2.8), so the server has no
  usable share and only classical groups to pick from, and must answer HelloRetryRequest
  for a classical group. **Expected to fail earlier than Finished:** the honest client already
  sent an X25519 share, and RFC 8446 §4.2.8 requires the client to verify that an HRR's
  `selected_group` was in its `supported_groups` and was *not* already in its original
  `key_share` (and §4.1.4: abort with `illegal_parameter` if the HRR "would not result in any
  change in the ClientHello"). If the server's HRR names X25519, the client aborts at the HRR.  Only an HRR for a group the client offered without a share (e.g. secp256r1) reaches the
  §4.4.1 `message_hash` path, and then fails at Finished. Which one happens depends on the
  server's group preference; the live test will show it. Either way: no downgrade.

**The hard part — ClientHello split across Initials.** A PQ ClientHello is 1446–1519 B
(claim C-04) and spans ≥2 client Initial packets, so it is carried as CRYPTO fragments
at different offsets. The tool reassembles by CRYPTO offset (like `decode_initial`),
rewrites the whole message, then re-emits it as a single `CRYPTO[offset=0]` frame in the
Initial that originally carried offset 0, **padded back to the original packet size**;
any other Initial that carried ClientHello CRYPTO is replaced by all-PADDING of the same
size. This preserves packet numbers, datagram count, and datagram sizes, so **no ACK or
packet-number translation is needed** — the single simplification that makes the live
relay tractable. Not handled: Retry (client re-keys off the server SCID, RFC 9000
§17.2.5 — the tool raises), 0-RTT, coalesced client Initial+Handshake datagrams.

### Offline results (verified now)

`data/go-go.jsonl` (claim C-01) as fixture. `python harness/tap/test_downgrade_proxy.py`
→ **8/8 pass**, including re-encryption-is-inverse on 5 real Initials and a full-trace
rewrite re-decoded through the honest server's own parser:

- strip: ClientHello 1511 B → 289 B; server's view `supported_groups` loses
  `X25519MLKEM768`, `key_shares` = `[(X25519, 32)]` (a tolerant server picks X25519).
- hrr-force: 1511 B → 249 B; `supported_groups` = `[X25519, secp256r1, secp384r1,
  secp521r1]` (all classical), `key_shares` = `[]`.

Reproduce:
```
cd harness/tap
python test_downgrade_proxy.py
python downgrade_proxy.py --check ../../data/go-go.jsonl --mode strip
python downgrade_proxy.py --check ../../data/go-go.jsonl --mode hrr-force
```

### Live test (for the user to run later; DO NOT run while a measurement is live)

The relay is implemented but **not run live this session**. It is a drop-in
replacement for `quic_tap.py` in the pipeline: the dialer targets the proxy's
`--listen` port and the proxy forwards to the listener's `--upstream` port. The pair
CLIs are verified from source — go-pair uses flags (`main.go:92-96`), rust-pair uses
positional args (`main.rs:79-94`).

```
# go-libp2p: listener on 5551, proxy 5550 -> 5551, dialer -> 5550
harness/go-pair/gopair.exe -mode listen -listen-port 5551 -seconds 30   # prints: peer <id>
python harness/tap/downgrade_proxy.py --mode strip --listen 5550 --upstream 5551 --seconds 30 &
harness/go-pair/gopair.exe -mode dial -dial-port 5550 -peer <listener-peerid>

# rust-libp2p: positional args  (rust-pair listen <port> [secs] | dial <port> <peer-id>)
harness/rust-pair/target/release/rust-pair.exe listen 5551 30            # prints: peer <id>
python harness/tap/downgrade_proxy.py --mode strip --listen 5550 --upstream 5551 --seconds 30 &
harness/rust-pair/target/release/rust-pair.exe dial 5550 <listener-peerid>
```
Or reuse `harness/run_pair.sh` with `tap/quic_tap.py` swapped for
`tap/downgrade_proxy.py --mode strip` (it wires `__LP__`=listener, `__TP__`=proxy,
`__PEER__`=peer id). Expected: the dialer
fails the handshake. In `strip`, the server emits a ServerHello selecting X25519 and
then the client aborts at its Finished; in `hrr-force`, a HelloRetryRequest, then
either an immediate client `illegal_parameter` abort (HRR names X25519, already shared) or a
Finished failure (HRR names a group offered without a share). A *pass* for RQ5 is the handshake failing —
confirm there is **no** second dial attempt offering a classical-only ClientHello.

## 7. Unverified / open

- **js-libp2p retry path not line-cited.** `@chainsafe/libp2p-quic` 2.1.5 is a minified
  native addon; the no-retry claim rests on it sharing the quinn/rustls backend (C-14),
  not on a grep of its source. To close: inspect the `@chainsafe/libp2p-quic` Rust crate
  source (not node_modules) for any `ClientConfig` rebuild on error.
- **Live outcome is a prediction, not a measurement** (strip → ServerHello(X25519) then
  client-Finished failure; hrr-force → HRR then failure). The relay's live path (and its
  Retry/0-RTT/coalescing limits) has not been exercised against peers.
- **go-libp2p/quic-go swarm-level retry** was argued from the fixed per-transport config,
  not traced end-to-end through `go-libp2p` dial retry loops. The grep of
  `p2p/transport/quic` + `p2p/security/tls` is clean, but a determined reviewer would
  want the swarm/basichost retry loop shown to reuse the same `tls.Config`.
- RFC 8446 §4.1.3 (sentinels: TLS 1.2 and below only), §4.1.4 (abort if HRR changes
  nothing), §4.2.8 (HRR `selected_group` checks; `client_shares` MAY be empty when requesting
  HRR) and §4.4.1 (`message_hash` replaces ClientHello1) were checked against
  rfc-editor.org/rfc/rfc8446.txt on 2026-10-28. The RFC 9000/9001/9002 section numbers
  above have not been re-checked.
