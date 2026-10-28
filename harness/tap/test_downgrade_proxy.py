"""Offline unit tests for downgrade_proxy, run against recorded census traces.

Run from harness/tap/:  python test_downgrade_proxy.py   (also pytest-compatible)

The fixture is data/go-go.jsonl (claim C-01): a real go-libp2p ClientHello that
offers X25519MLKEM768 (0x11EC) + X25519 and spans several Initial packets.
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
DATA = os.path.normpath(os.path.join(HERE, "..", "..", "data"))

import decode_initial  # noqa: E402
from downgrade_proxy import (  # noqa: E402
    X25519MLKEM768,
    _decode_initial,
    _encrypt_initial,
    encode_varint,
    initial_keys,
    rewrite_client_hello,
    rewrite_trace,
    split_datagram,
)

FIXTURE = os.path.join(DATA, "go-go.jsonl")


def _load(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _reassemble_ch(records):
    """Pull the raw ClientHello handshake message out of a recorded trace."""
    dcid, frames = None, []
    for rec in records:
        if rec.get("dir") != "c2s":
            continue
        pkts = split_datagram(bytes.fromhex(rec["hex"]))
        if not pkts or pkts[0].ptype != 0:
            continue
        if dcid is None:
            dcid = pkts[0].dcid
        _, _, _, pt = _decode_initial(pkts[0], initial_keys(dcid, "client"))
        fr, _ = decode_initial.crypto_frames(pt)
        frames.extend(fr)
    msgs = decode_initial.handshake_messages(decode_initial.assemble(frames))
    mtype, body = msgs[0]
    return bytes([mtype]) + len(body).to_bytes(3, "big") + body


# --- varint round-trip ------------------------------------------------------

def test_varint_roundtrip():
    for v in [0, 1, 63, 64, 289, 16383, 16384, 1216, 1 << 20, (1 << 30) - 1]:
        enc = encode_varint(v)
        got, pos = decode_initial.read_varint(enc, 0)
        assert got == v and pos == len(enc), (v, enc.hex(), got, pos)


# --- re-encryption is the exact inverse of decryption -----------------------

def test_encrypt_is_inverse_of_decrypt():
    records = _load(FIXTURE)
    dcid = None
    checked = 0
    for rec in records:
        if rec.get("dir") != "c2s":
            continue
        pkts = split_datagram(bytes.fromhex(rec["hex"]))
        if not pkts or pkts[0].ptype != 0:
            continue
        if dcid is None:
            dcid = pkts[0].dcid
        keys = initial_keys(dcid, "client")
        hdr, pn, pn_len, pt = _decode_initial(pkts[0], keys)
        rebuilt = _encrypt_initial(hdr, pn, pn_len, pt, keys, pkts[0].pn_offset)
        assert rebuilt == pkts[0].raw, f"re-encrypt mismatch on pn={pn}"
        checked += 1
    assert checked >= 1
    print(f"  re-encryption inverse verified on {checked} client Initial(s)")


# --- the fixture really contains the hybrid (guards against a stale fixture) -

def test_fixture_has_hybrid():
    ch = _reassemble_ch(_load(FIXTURE))
    assert ch[0] == 1, "fixture first message is not a ClientHello"
    before = decode_initial.parse_client_hello(ch[4:])
    assert "X25519MLKEM768" in before["supported_groups"]
    assert any(g == "X25519MLKEM768" for g, _ in before["key_shares"])
    assert any(g == "X25519" for g, _ in before["key_shares"]), "need X25519 share too"


# --- strip: pure ClientHello rewrite ----------------------------------------

def test_strip_removes_only_the_hybrid():
    ch = _reassemble_ch(_load(FIXTURE))
    new_ch, changed = rewrite_client_hello(ch, X25519MLKEM768, mode="strip")
    assert changed
    after = decode_initial.parse_client_hello(new_ch[4:])
    assert "X25519MLKEM768" not in after["supported_groups"]
    assert all(g != "X25519MLKEM768" for g, _ in after["key_shares"])
    # strip leaves the classical X25519 share so a tolerant server can pick it
    assert any(g == "X25519" for g, _ in after["key_shares"])
    # other classical groups are untouched
    assert "secp256r1" in after["supported_groups"]
    # the handshake-message length field is consistent with the new body
    assert int.from_bytes(new_ch[1:4], "big") == len(new_ch) - 4
    # and it is shorter (hybrid share is ~1216 B)
    assert len(new_ch) < len(ch)


def test_strip_idempotent_when_group_absent():
    ch = _reassemble_ch(_load(FIXTURE))
    new_ch, _ = rewrite_client_hello(ch, X25519MLKEM768, mode="strip")
    again, changed = rewrite_client_hello(new_ch, X25519MLKEM768, mode="strip")
    assert not changed and again == new_ch


# --- hrr-force: empties the key_share vector --------------------------------

def test_hrr_force_empties_key_share():
    ch = _reassemble_ch(_load(FIXTURE))
    new_ch, changed = rewrite_client_hello(ch, X25519MLKEM768, mode="hrr-force")
    assert changed
    after = decode_initial.parse_client_hello(new_ch[4:])
    assert after["key_shares"] == [], "hrr-force must leave no key shares"
    # hrr-force removes ALL hybrid/PQ groups so the HRR must be for a classical group
    for g in after["supported_groups"]:
        assert "MLKEM" not in g and "Kyber" not in g, f"PQ group {g} survived hrr-force"
    # classical groups remain for the server to HRR for
    assert "X25519" in after["supported_groups"]
    assert "secp256r1" in after["supported_groups"]


# --- full trace rewrite, verified through the server's decoder ---------------

def test_rewrite_trace_strip_server_view():
    records = _load(FIXTURE)
    out, summary = rewrite_trace(records, mode="strip")
    assert summary["client_hello_changed"]
    assert summary["rewritten_packets"] >= 1
    # datagram count and per-datagram sizes are preserved
    assert len(out) == len(records)
    for a, b in zip(records, out):
        assert len(bytes.fromhex(a["hex"])) == len(bytes.fromhex(b["hex"]))
    # decode the rewritten trace exactly as the honest server would
    view = decode_initial.analyse(out)
    ch = next(h["ClientHello"] for h in view["c2s"]["hellos"] if "ClientHello" in h)
    assert "X25519MLKEM768" not in ch["supported_groups"]
    assert all(g != "X25519MLKEM768" for g, _ in ch["key_shares"])
    assert any(g == "X25519" for g, _ in ch["key_shares"])
    # the server still gets a valid ServerHello-less view: its CH parses clean
    assert ch["length"] == summary["rewritten_ch_len"]
    print(f"  server sees groups={ch['supported_groups']} shares={ch['key_shares']}")


def test_rewrite_trace_hrr_server_view():
    out, summary = rewrite_trace(_load(FIXTURE), mode="hrr-force")
    view = decode_initial.analyse(out)
    ch = next(h["ClientHello"] for h in view["c2s"]["hellos"] if "ClientHello" in h)
    assert "X25519MLKEM768" not in ch["supported_groups"]
    assert ch["key_shares"] == []


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"FAIL {t.__name__}: {e!r}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run_all())
