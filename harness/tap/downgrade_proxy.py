"""On-path downgrade proxy for libp2p-QUIC (RQ5), offline-first.

An on-path attacker CAN read and rewrite QUIC v1 Initial packets, because their
AEAD keys are derived from the client's Destination Connection ID (RFC 9001
section 5.2), not from any secret. This tool rewrites the TLS ClientHello carried
in client Initial packets to remove the hybrid group, to test whether the libp2p
stacks detect the tampering (they must: the ClientHello is bound into the TLS 1.3
transcript, RFC 8446 sections 4.4.1/4.4.4, so any change makes the server's
Finished/CertificateVerify fail at the honest client).

Two rewrite modes:
  strip     - delete the X25519MLKEM768 (0x11EC) entry from supported_groups
              (RFC 8446 section 4.2.7) and its KeyShareEntry from key_share
              (section 4.2.8). The X25519 share is left in place, so a tolerant
              server can still select X25519 - but the honest client's transcript
              still contains the hybrid, so the handshake must fail.
  hrr-force - delete 0x11EC from supported_groups AND empty the client_shares
              vector, so the server has no usable share for any offered group and
              must answer with HelloRetryRequest for a classical group. Exercises
              the HRR synthetic message_hash transcript rule (RFC 8446 4.4.1).

This module reuses the RFC-9001-Appendix-A-checked key schedule and packet
parsing from decode_initial.py. It never forges a handshake: it only strips, so
the expected outcome against a correct stack is handshake FAILURE, which is the
positive result for the research question.

The offline path (rewrite_trace / --check) is fully exercised by the unit tests.
The live UDP relay (DowngradeProxy) is modelled on quic_tap.py; see LIMITATIONS
at the bottom of this file for exactly what is and is not handled live.
"""

import argparse
import json
import selectors
import socket
import sys

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from decode_initial import (
    QUIC_V1,
    LongPacket,
    assemble,
    crypto_frames,
    handshake_messages,
    initial_keys,
    read_varint,
    split_datagram,
)

X25519MLKEM768 = 0x11EC
# Post-quantum / hybrid NamedGroup code points (RFC 8446 registry; see
# decode_initial.GROUPS). hrr-force removes all of these so the server is forced to
# HelloRetryRequest for a purely classical group.
PQ_GROUPS = frozenset({0x0200, 0x0201, 0x0202, 0x11EB, 0x11EC, 0x11ED, 0x6399})
EXT_SUPPORTED_GROUPS = 0x000A
EXT_KEY_SHARE = 0x0033
HANDSHAKE_CLIENT_HELLO = 1
FRAME_CRYPTO = 0x06
FRAME_PADDING = 0x00


# --- QUIC varint encoding (RFC 9000 section 16) -----------------------------

def encode_varint(value: int) -> bytes:
    if value < 0:
        raise ValueError("varint must be non-negative")
    if value < (1 << 6):
        return bytes([value])
    if value < (1 << 14):
        return (value | 0x4000).to_bytes(2, "big")
    if value < (1 << 30):
        return (value | 0x80000000).to_bytes(4, "big")
    if value < (1 << 62):
        return (value | 0xC000000000000000).to_bytes(8, "big")
    raise ValueError("varint too large")


def u16(buf: bytes, pos: int = 0) -> int:
    return int.from_bytes(buf[pos : pos + 2], "big")


# --- TLS ClientHello rewriting ----------------------------------------------

def _strip_from_supported_groups(ext_body: bytes, remove: set) -> bytes:
    """supported_groups is a NamedGroup vector (RFC 8446 section 4.2.7)."""
    list_len = u16(ext_body)
    groups = ext_body[2 : 2 + list_len]
    kept = b"".join(
        groups[i : i + 2] for i in range(0, len(groups), 2) if u16(groups, i) not in remove
    )
    return len(kept).to_bytes(2, "big") + kept


def _rewrite_key_share(ext_body: bytes, group: int, drop_all: bool) -> bytes:
    """key_share client_shares is KeyShareEntry* (RFC 8446 section 4.2.8)."""
    shares_len = u16(ext_body)
    data = ext_body[2 : 2 + shares_len]
    kept, pos = b"", 0
    while pos + 4 <= len(data):
        g = u16(data, pos)
        klen = u16(data, pos + 2)
        entry = data[pos : pos + 4 + klen]
        if not (drop_all or g == group):
            kept += entry
        pos += 4 + klen
    return len(kept).to_bytes(2, "big") + kept


def _rewrite_extensions(exts: bytes, group: int, mode: str) -> tuple[bytes, bool]:
    """Walk the extension list, rewrite the two KEX extensions, keep order."""
    remove = set(PQ_GROUPS) if mode == "hrr-force" else {group}
    out, pos, touched = b"", 0, False
    while pos + 4 <= len(exts):
        etype = u16(exts, pos)
        elen = u16(exts, pos + 2)
        body = exts[pos + 4 : pos + 4 + elen]
        if etype == EXT_SUPPORTED_GROUPS:
            new = _strip_from_supported_groups(body, remove)
            touched = touched or new != body
            body = new
        elif etype == EXT_KEY_SHARE:
            new = _rewrite_key_share(body, group, drop_all=(mode == "hrr-force"))
            touched = touched or new != body
            body = new
        out += exts[pos : pos + 2] + len(body).to_bytes(2, "big") + body
        pos += 4 + elen
    return out, touched


def _extensions_offset(body: bytes) -> int:
    """Offset of the 2-byte extensions-length field inside a ClientHello body."""
    pos = 2 + 32  # legacy_version + random
    pos += 1 + body[pos]  # legacy_session_id
    pos += 2 + u16(body, pos)  # cipher_suites
    pos += 1 + body[pos]  # legacy_compression_methods
    return pos


def rewrite_client_hello(ch_message: bytes, group: int = X25519MLKEM768,
                         mode: str = "strip") -> tuple[bytes, bool]:
    """Rewrite a ClientHello handshake message (type||len24||body).

    Returns (new_message, changed). `changed` is False when the group was absent,
    in which case the message is returned unchanged.
    """
    if mode not in ("strip", "hrr-force"):
        raise ValueError(f"unknown mode {mode!r}")
    if not ch_message or ch_message[0] != HANDSHAKE_CLIENT_HELLO:
        raise ValueError("not a ClientHello handshake message")
    body = bytearray(ch_message[4:])
    ext_len_pos = _extensions_offset(body)
    ext_start = ext_len_pos + 2
    exts = bytes(body[ext_start:])
    new_exts, changed = _rewrite_extensions(exts, group, mode)
    if not changed:
        return ch_message, False
    body[ext_len_pos:ext_len_pos + 2] = len(new_exts).to_bytes(2, "big")
    body[ext_start:] = new_exts
    new_body = bytes(body)
    return bytes([HANDSHAKE_CLIENT_HELLO]) + len(new_body).to_bytes(3, "big") + new_body, True


# --- Initial packet re-encryption (inverse of decode_initial.decrypt_initial) -

def _decode_initial(pkt: LongPacket, keys) -> tuple[bytes, int, int, bytes]:
    """Return (header_without_pn, packet_number, pn_len, plaintext_payload)."""
    raw = bytearray(pkt.raw)
    sample = bytes(raw[pkt.pn_offset + 4 : pkt.pn_offset + 20])
    enc = Cipher(algorithms.AES(keys.hp), modes.ECB()).encryptor()
    mask = enc.update(sample) + enc.finalize()
    raw[0] ^= mask[0] & 0x0F
    pn_len = (raw[0] & 0x03) + 1
    pn = 0
    for i in range(pn_len):
        raw[pkt.pn_offset + i] ^= mask[1 + i]
        pn = (pn << 8) | raw[pkt.pn_offset + i]
    header = bytes(raw[: pkt.pn_offset + pn_len])
    nonce = bytes(a ^ b for a, b in zip(keys.iv, pn.to_bytes(12, "big")))
    plaintext = AESGCM(keys.key).decrypt(nonce, bytes(raw[pkt.pn_offset + pn_len:]), header)
    return header[: pkt.pn_offset], pn, pn_len, plaintext


def _encrypt_initial(header_wo_pn: bytes, pn: int, pn_len: int, plaintext: bytes,
                     keys, pn_offset: int) -> bytes:
    """Rebuild a protected Initial packet. Keeps the Length field valid only if
    len(plaintext) matches the original (ciphertext grows by the 16-byte tag)."""
    header = bytearray(header_wo_pn) + pn.to_bytes(pn_len, "big")
    nonce = bytes(a ^ b for a, b in zip(keys.iv, pn.to_bytes(12, "big")))
    ct = AESGCM(keys.key).encrypt(nonce, plaintext, bytes(header))
    packet = bytearray(header) + ct
    sample = bytes(packet[pn_offset + 4 : pn_offset + 20])
    enc = Cipher(algorithms.AES(keys.hp), modes.ECB()).encryptor()
    mask = enc.update(sample) + enc.finalize()
    packet[0] ^= mask[0] & 0x0F
    for i in range(pn_len):
        packet[pn_offset + i] ^= mask[1 + i]
    return bytes(packet)


def _crypto_frame(offset: int, data: bytes) -> bytes:
    return bytes([FRAME_CRYPTO]) + encode_varint(offset) + encode_varint(len(data)) + data


def _pad_to(frames: bytes, total: int) -> bytes:
    if len(frames) > total:
        raise ValueError(f"rewritten payload {len(frames)} exceeds packet room {total}")
    return frames + bytes([FRAME_PADDING]) * (total - len(frames))


def _offsets_in(plaintext: bytes) -> list[int]:
    frames, _ = crypto_frames(plaintext)
    return [off for off, _ in frames]


# --- Trace rewriting (offline) ----------------------------------------------

def rewrite_trace(records: list[dict], mode: str = "strip",
                  group: int = X25519MLKEM768) -> tuple[list[dict], dict]:
    """Rewrite the client Initial packets in a recorded quic_tap trace.

    Strategy that needs no packet-number or ACK translation: the rewritten (now
    short) ClientHello is placed, whole, in a single CRYPTO[0] frame in the
    client Initial that originally carried CRYPTO offset 0, padded back to the
    original packet size; any other client Initial that carried ClientHello
    CRYPTO is replaced by all-PADDING of the same size. Packet numbers, datagram
    count and datagram sizes are all preserved.
    """
    dcid = None
    c2s_initials: list[tuple[int, LongPacket, bytes]] = []  # (rec_idx, pkt, plaintext)
    frames_all: list[tuple[int, bytes]] = []

    for idx, rec in enumerate(records):
        if rec.get("dir") != "c2s":
            continue
        data = bytes.fromhex(rec["hex"])
        pkts = split_datagram(data)
        if not pkts or pkts[0].ptype != 0:
            continue
        if pkts[0].version != QUIC_V1:
            raise ValueError(f"QUIC version 0x{pkts[0].version:08x} not supported")
        if any(p.ptype == 3 for p in pkts):
            raise ValueError("Retry present: not handled, re-key needed")
        if dcid is None:
            dcid = pkts[0].dcid
        keys = initial_keys(dcid, "client")
        _, _, _, pt = _decode_initial(pkts[0], keys)
        fr, _ = crypto_frames(pt)
        frames_all.extend(fr)
        c2s_initials.append((idx, pkts[0], pt))

    if dcid is None:
        raise ValueError("no client Initial found in trace")

    msgs = handshake_messages(assemble(frames_all))
    if not msgs or msgs[0][0] != HANDSHAKE_CLIENT_HELLO:
        raise ValueError("first client handshake message is not a ClientHello")
    ch_msg = bytes([msgs[0][0]]) + len(msgs[0][1]).to_bytes(3, "big") + msgs[0][1]
    new_ch, changed = rewrite_client_hello(ch_msg, group, mode)

    keys = initial_keys(dcid, "client")
    out = [dict(r) for r in records]
    rewritten_packets = 0
    for idx, pkt, pt in c2s_initials:
        offsets = _offsets_in(pt)
        if not offsets:
            continue  # ACK/PADDING-only Initial: leave untouched
        if 0 in offsets:
            new_pt = _pad_to(_crypto_frame(0, new_ch), len(pt))
        else:
            new_pt = bytes([FRAME_PADDING]) * len(pt)
        hdr, pn, pn_len, _ = _decode_initial(pkt, keys)
        new_pkt = _encrypt_initial(hdr, pn, pn_len, new_pt, keys, pkt.pn_offset)
        remainder = bytes.fromhex(out[idx]["hex"])[len(pkt.raw):]
        new_data = new_pkt + remainder
        out[idx]["hex"] = new_data.hex()
        out[idx]["len"] = len(new_data)
        rewritten_packets += 1

    summary = {
        "mode": mode,
        "group": f"0x{group:04x}",
        "dcid": dcid.hex(),
        "client_hello_changed": changed,
        "original_ch_len": len(ch_msg),
        "rewritten_ch_len": len(new_ch),
        "c2s_initials": len(c2s_initials),
        "rewritten_packets": rewritten_packets,
    }
    return out, summary


# --- Live UDP relay (modelled on quic_tap.Tap) ------------------------------

class _Conn:
    """Per-client state: buffer client Initials until the ClientHello completes."""

    def __init__(self):
        self.dcid: bytes | None = None
        self.buffered: list[bytes] = []  # raw c2s datagrams held back
        self.done = False  # ClientHello rewritten and flushed


class DowngradeProxy:
    """UDP relay that rewrites the ClientHello in-flight. See LIMITATIONS below.

    Dialers send to --listen; the proxy forwards to --upstream and back, holding
    client Initial datagrams until the ClientHello is complete, then rewriting and
    releasing them (packet numbers preserved). All later datagrams pass through.
    """

    def __init__(self, listen_port: int, upstream_port: int, mode: str,
                 group: int = X25519MLKEM768):
        self.front = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.front.bind(("127.0.0.1", listen_port))
        self.upstream = ("127.0.0.1", upstream_port)
        self.mode = mode
        self.group = group
        self.sel = selectors.DefaultSelector()
        self.sel.register(self.front, selectors.EVENT_READ, None)
        self.backs: dict[tuple, socket.socket] = {}
        self.conns: dict[tuple, _Conn] = {}

    def _back_for(self, client: tuple) -> socket.socket:
        if client not in self.backs:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.bind(("127.0.0.1", 0))
            self.sel.register(s, selectors.EVENT_READ, client)
            self.backs[client] = s
            self.conns[client] = _Conn()
        return self.backs[client]

    def _rewrite_buffered(self, conn: _Conn) -> list[bytes] | None:
        """Try to rewrite the buffered client Initials. None if CH not complete yet."""
        fake = [{"dir": "c2s", "hex": d.hex(), "len": len(d)} for d in conn.buffered]
        try:
            out, _ = rewrite_trace(fake, self.mode, self.group)
        except ValueError:
            return None  # ClientHello not yet fully assembled; keep buffering
        return [bytes.fromhex(r["hex"]) for r in out]

    def _handle_c2s(self, data: bytes, client: tuple, back: socket.socket) -> None:
        conn = self.conns[client]
        if conn.done:
            back.sendto(data, self.upstream)
            return
        pkts = split_datagram(data)
        if not pkts or pkts[0].ptype != 0:  # not an Initial: let it through
            back.sendto(data, self.upstream)
            return
        conn.buffered.append(data)
        flushed = self._rewrite_buffered(conn)
        if flushed is None:
            return
        for d in flushed:
            back.sendto(d, self.upstream)
        conn.buffered.clear()
        conn.done = True

    def run(self, seconds: float) -> int:
        import time
        start = time.monotonic()
        print(f"downgrade-proxy {self.mode} 127.0.0.1:{self.front.getsockname()[1]} "
              f"-> {self.upstream[1]}", flush=True)
        while time.monotonic() - start < seconds:
            for key, _ in self.sel.select(timeout=0.2):
                sock, client = key.fileobj, key.data
                try:
                    data, addr = sock.recvfrom(65535)
                except (ConnectionResetError, OSError):
                    continue
                if client is None:
                    self._handle_c2s(data, addr, self._back_for(addr))
                else:
                    self.front.sendto(data, client)
        print("downgrade-proxy done", flush=True)
        return 0


# --- CLI --------------------------------------------------------------------

def _check(trace_path: str, mode: str) -> int:
    import decode_initial
    with open(trace_path, encoding="utf-8") as f:
        records = [json.loads(line) for line in f if line.strip()]
    out, summary = rewrite_trace(records, mode)
    print(json.dumps(summary, indent=2))
    server_view = decode_initial.analyse(out)
    hellos = server_view["c2s"]["hellos"]
    ch = next((h["ClientHello"] for h in hellos if "ClientHello" in h), None)
    if ch is None:
        print("FAIL: rewritten trace has no parseable ClientHello", file=sys.stderr)
        return 1
    print(json.dumps({"server_sees": {
        "supported_groups": ch["supported_groups"],
        "key_shares": ch["key_shares"],
        "length": ch["length"],
    }}, indent=2))
    if "X25519MLKEM768" in ch["supported_groups"] or \
            any(g == "X25519MLKEM768" for g, _ in ch["key_shares"]):
        print("FAIL: X25519MLKEM768 still present after rewrite", file=sys.stderr)
        return 1
    print("ok: server would see a ClientHello without X25519MLKEM768")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--mode", choices=["strip", "hrr-force"], default="strip")
    p.add_argument("--check", metavar="TRACE",
                   help="offline: rewrite a recorded trace and show the server's view")
    p.add_argument("--listen", type=int, help="live: UDP port dialers connect to")
    p.add_argument("--upstream", type=int, help="live: listener UDP port")
    p.add_argument("--seconds", type=float, default=30.0)
    a = p.parse_args()
    if a.check:
        return _check(a.check, a.mode)
    if a.listen and a.upstream:
        return DowngradeProxy(a.listen, a.upstream, a.mode).run(a.seconds)
    p.error("give --check TRACE, or both --listen and --upstream")
    return 2


if __name__ == "__main__":
    sys.exit(main())


# --- LIMITATIONS (live relay) -----------------------------------------------
# The offline rewrite_trace path and the pure ClientHello rewrite are covered by
# test_downgrade_proxy.py. The live DowngradeProxy is implemented but has NOT been
# run against live peers in this session (a timing measurement was running). What
# it handles and what it does not, explicitly:
#  * Handled: client ClientHello split across several Initial packets (it buffers
#    them, reassembles via CRYPTO offsets, rewrites, and releases with packet
#    numbers, datagram count and sizes preserved, so no ACK/PN translation is
#    needed). s2c is passed through untouched.
#  * NOT handled: a Retry (rewrite_trace raises; the client re-keys Initials off
#    the server-chosen SCID, RFC 9000 section 17.2.5, so keys and the buffer would
#    have to reset). 0-RTT. Coalesced Initial+Handshake client datagrams (only the
#    leading Initial is rewritten; the remainder is forwarded verbatim). A
#    ClientHello that does not start at CRYPTO offset 0 in some packet.
#  * By design it does NOT forge a handshake. Against a correct TLS 1.3 stack the
#    honest client's transcript still contains the hybrid, so the expected live
#    outcome is handshake failure (transcript/Finished mismatch) or, in hrr-force,
#    an extra HelloRetryRequest round trip that still fails the final Finished.
