# CLAIMS — PQ-QUIC

Every number that reaches prose comes from this file, and every row points at its evidence.

## Verified

| ID | Claim | Evidence |
|---|---|---|
| C-01 | go-libp2p v0.51.0 (quic-go v0.64.1, Go 1.26.10), go↔go on loopback: ClientHello offers `X25519MLKEM768, SecP256r1MLKEM768, SecP384r1MLKEM1024, X25519, secp256r1, secp384r1, secp521r1`; sends two key shares (X25519MLKEM768 1,216 B + X25519 32 B); ClientHello 1,511 B; server selects X25519MLKEM768 (share 1,120 B), no HRR | `data/go-go.jsonl`, 2026-10-26, decoded by `harness/tap/decode_initial.py` |
| C-02 | rust-libp2p 0.57.1 (libp2p-quic 0.14.0, libp2p-tls 0.7.0, rustls aws-lc-rs + prefer-post-quantum), rust↔rust on loopback: offers `X25519MLKEM768, X25519, secp256r1, secp384r1`; two key shares (1,216 B + 32 B); ClientHello 1,495 B; server selects X25519MLKEM768, no HRR | `data/rust-rust.jsonl`, 2026-10-26 |
| C-03 | aioquic 1.2.0 control (not libp2p): offers `secp256r1, secp384r1, X25519, X448` with four key shares; ClientHello 456 B; aioquic server selects secp256r1 | `data/control-aioquic.jsonl`, 2026-10-26 |
| C-04 | In both C-01 and C-02 the ClientHello (≥1,495 B) is larger than one client Initial datagram (1,280 B Go, 1,200 B Rust), so it spans at least two Initial packets | arithmetic on C-01/C-02 lengths and datagram sizes in the traces |

| C-05 | aioquic PR #634 head `3052209` (cryptography 50.0.2), default config, as a libp2p QUIC peer: client ↔ go-libp2p v0.51.0 and ↔ rust-libp2p 0.57.1, both directions, select X25519MLKEM768 and complete; go and rust listeners log `accepted <peer id>` for the aioquic identity | `data/634-{aioquic-to-go,aioquic-to-rust,go-to-aioquic,rust-to-aioquic}.jsonl` + run logs, 2026-10-26 |
| C-06 | PR #634 default client offers 5 groups with 5 key shares (X25519MLKEM768 1,216, X25519 32, P-256 65, P-384 97, X448 56); ClientHello 1,678 B | `data/634-aioquic-to-go.jsonl` |
| C-07 | PR #634 client restricted to `SECP256R1MLKEM768` → go-libp2p: Go selects SecP256r1MLKEM768 (client share 1,249 B = 65 + 1,184; server share 1,153 B = 65 + 1,088), handshake completes, go accepts. Same for `SECP384R1MLKEM1024` (shares 1,665 / 1,665; ClientHello 1,853 B) | `data/634-aioquic-to-go-SecP256r1MLKEM768.jsonl`, `...SecP384r1MLKEM1024.jsonl` |
| C-08 | PR #634 server restricted to SECP256R1MLKEM768 or SECP384R1MLKEM1024, go client (lists both, shares only X25519MLKEM768 + X25519): aioquic sends CONNECTION_CLOSE 0x128 "No supported key share" instead of HelloRetryRequest. Same code path exists on aioquic `main` (no HRR in aioquic): pre-existing, not a PR regression | `data/634-go-to-aioquic-SecP*.jsonl`; `git grep "No supported key share"` on main and pr634 |
| C-09 | PR #634 `GROUP_NAMES` does not accept the IANA spellings `SecP256r1MLKEM768` / `SecP384r1MLKEM1024` (registry 4587/4589, RFC 10024); a bad name raises `KeyError: <Epoch.INITIAL: 0>` on the client, `ValueError: Unknown TLS group` on the server | PR source `tls.py:1163-1190`; IANA tls-parameters-8.csv; run logs |

| C-10 | py-libp2p 0.8.1 with aioquic 1.7.0 (latest release, cryptography 50.0.2): as client offers only `secp256r1, secp384r1, X25519, X448` (ClientHello 452 B); go and rust listeners accept; Go picks X25519, rustls picks secp256r1. As server it picks X25519 from go/rust ClientHellos that offer X25519MLKEM768. All four pairs connect classical-only | `data/pylibp2p-{py-to-go,go-to-py,py-to-rust,rust-to-py}.jsonl`, 2026-10-26 |
| C-11 | Same py-libp2p 0.8.1 with aioquic replaced by PR #634 head `3052209` (`--no-deps`), no py-libp2p change: all four pairs select X25519MLKEM768 and connect (py client ClientHello 1,674 B, 5 shares). One py→go attempt produced no datagrams at all (launcher glitch); two reruns passed | `data/pylibp2p-{py634-to-go,go-to-py634,py634-to-rust,rust-to-py634}.jsonl` |

| C-12 | go-libp2p v0.51.0 ↔ rust-libp2p 0.57.1, both directions: X25519MLKEM768 selected, listener accepts; ClientHello 1,519 B (go) / 1,490 B (rust) | `data/go-to-rust.jsonl`, `data/rust-to-go.jsonl`, 2026-10-26 |
| C-13 | Classical baselines on the same builds: Go with `GODEBUG=tlsmlkem=0` offers X25519, secp256r1, secp384r1, secp521r1 with one X25519 share (ClientHello 287 B). Rust with the harness patch `PQQUIC_CLASSICAL=1` (vendored libp2p-tls 0.7.0, `kx_groups = [X25519]`) offers only X25519 (ClientHello 266 B). Both connect | `data/go-go-classical.jsonl`, `data/rust-rust-classical.jsonl`; patch in `harness/rust-pair/vendor/libp2p-tls/src/lib.rs` |
| C-14 | js-libp2p 3.5.1 + @chainsafe/libp2p-quic 2.1.5 (Node 22.17.1, win32-x64 prebuilt): js↔js, js↔go and js↔rust in both directions select X25519MLKEM768; js offers X25519MLKEM768, X25519, secp256r1, secp384r1 (two shares, ClientHello 1,484–1,491 B). The `ring` dependency does not displace the aws-lc-rs PQ provider | `data/{js-js,js-to-go,go-to-js,js-to-rust,rust-to-js}.jsonl`. Note: the first decode of `js-to-go.jsonl` errored inside the shell pipeline; re-decoding the same unchanged file succeeds |
| C-15 | Chrome 155.0.8059.85 (headless, throwaway profile) WebTransport → go-libp2p v0.51.0 WebTransport listener (certhash): offers X25519MLKEM768, X25519, secp256r1, secp384r1 (two shares, ClientHello 1,469 B); go selects X25519MLKEM768; `wt.ready` resolves. Only the QUIC/TLS step was run, not the Noise step inside WebTransport | `data/chrome-to-go-wt.jsonl`, `harness/js-pair/browser_wt.mjs` |

| C-16 | Classical-only dialer → default PQ listener, no HelloRetryRequest: Go (`GODEBUG=tlsmlkem=0`) → rust selects X25519; Rust (`PQQUIC_CLASSICAL=1`) → go selects X25519. Both connect | `data/goclassical-to-rust.jsonl`, `data/rustclassical-to-go.jsonl` |

| C-17 | (pilot-grade) No measurable handshake latency cost for hybrid vs classical at 50 and 150 ms RTT without loss, go and rust: median paired ratios 0.99–1.01, IQRs within ±6%, 30 pairs per cell | `data/bench/pilot-20261026T172756Z/`, `notes/phase2-pilot.md` |
| C-18 | (pilot-grade) Targeted loss of the first client datagram at 50 ms RTT, trace handshake time median: hybrid 149.7 ms (go) / 147.4 ms (rust) vs classical 268.5 ms (go) / 1,077.3 ms (rust); no-drop baselines 66.9–70.4 ms. Mechanism seen in trace: hybrid's second ClientHello packet elicits a server Initial ACK, and the client resends part 1 at +89 ms; the classical client waits for its first probe timeout (+1,016 ms quinn) | `data/bench/targeted-20261026T173953Z/`, `notes/phase2-targeted-loss.md` |
| C-19 | (pilot-grade) Targeted loss of the second client datagram: hybrid 264.2 (go) / 271.4 (rust) ms; no ACK-based detection for a loss after the last acknowledged packet, so recovery waits for a probe timeout | same |

## Not yet measured

- nim-libp2p (lsquic + BoringSSL). Blocked 2026-10-26: building nim-libp2p master's dependencies needs a newer nimble (CI pins 0.24.1; local is 0.22.2), and fetching/building them was held for the author's approval.

## Method notes

- The decoder's key derivation is checked against RFC 9001 Appendix A.1 (`--self-test`).
- Datagram counts include ACK-only Initials (padded), so `initial_datagrams` is not "datagrams carrying the ClientHello". Do not quote it as such.

## Retracted

| ID | Was | Why |
|---|---|---|
| X-01 | "aioquic control will select X25519" (prediction before C-03) | it selected secp256r1 |
