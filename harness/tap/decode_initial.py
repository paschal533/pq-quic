"""Decode the TLS handshake carried in QUIC v1 Initial packets from a quic_tap trace.

Initial packets are protected with keys derived from the client's original
Destination Connection ID (RFC 9001 section 5.2), so any observer can read the
ClientHello and ServerHello. This prints offered groups, key shares, the
selected group, HelloRetryRequest, and packet/byte counts.
"""

import argparse
import json
import sys
from dataclasses import dataclass, field

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hmac import HMAC

QUIC_V1 = 0x00000001
INITIAL_SALT_V1 = bytes.fromhex("38762cf7f55934b34d179ae6a4c80cadccbb7f0a")
HRR_RANDOM = bytes.fromhex(
    "cf21ad74e59a6111be1d8c021e65b891c2a211167abb8c5e079e09e2c8a8339c"
)

GROUPS = {
    0x0017: "secp256r1", 0x0018: "secp384r1", 0x0019: "secp521r1",
    0x001D: "X25519", 0x001E: "X448",
    0x0200: "MLKEM512", 0x0201: "MLKEM768", 0x0202: "MLKEM1024",
    0x11EB: "SecP256r1MLKEM768", 0x11EC: "X25519MLKEM768",
    0x11ED: "SecP384r1MLKEM1024", 0x6399: "X25519Kyber768Draft00",
}
SIGALGS = {
    0x0403: "ecdsa_secp256r1_sha256", 0x0503: "ecdsa_secp384r1_sha384",
    0x0603: "ecdsa_secp521r1_sha512", 0x0807: "ed25519", 0x0808: "ed448",
    0x0804: "rsa_pss_rsae_sha256", 0x0805: "rsa_pss_rsae_sha384",
    0x0806: "rsa_pss_rsae_sha512", 0x0401: "rsa_pkcs1_sha256",
    0x0501: "rsa_pkcs1_sha384", 0x0601: "rsa_pkcs1_sha512",
    0x0904: "mldsa44", 0x0905: "mldsa65", 0x0906: "mldsa87",
}


def name(table: dict, code: int) -> str:
    if (code & 0x0F0F) == 0x0A0A and (code >> 8) == (code & 0xFF):
        return "GREASE"
    return table.get(code, f"0x{code:04x}")


# --- key schedule -----------------------------------------------------------

def hkdf_extract(salt: bytes, ikm: bytes) -> bytes:
    h = HMAC(salt, hashes.SHA256())
    h.update(ikm)
    return h.finalize()


def hkdf_expand_label(secret: bytes, label: str, length: int) -> bytes:
    full = b"tls13 " + label.encode()
    info = length.to_bytes(2, "big") + bytes([len(full)]) + full + b"\x00"
    out, block, i = b"", b"", 1
    while len(out) < length:
        h = HMAC(secret, hashes.SHA256())
        h.update(block + info + bytes([i]))
        block = h.finalize()
        out += block
        i += 1
    return out[:length]


@dataclass(frozen=True)
class Keys:
    key: bytes
    iv: bytes
    hp: bytes


def initial_keys(dcid: bytes, side: str) -> Keys:
    initial = hkdf_extract(INITIAL_SALT_V1, dcid)
    secret = hkdf_expand_label(initial, f"{side} in", 32)
    return Keys(
        hkdf_expand_label(secret, "quic key", 16),
        hkdf_expand_label(secret, "quic iv", 12),
        hkdf_expand_label(secret, "quic hp", 16),
    )


# --- packet parsing ---------------------------------------------------------

def read_varint(buf: bytes, pos: int) -> tuple[int, int]:
    first = buf[pos]
    length = 1 << (first >> 6)
    value = first & 0x3F
    for b in buf[pos + 1 : pos + length]:
        value = (value << 8) | b
    return value, pos + length


@dataclass
class LongPacket:
    ptype: int  # 0 Initial, 1 0-RTT, 2 Handshake, 3 Retry
    version: int
    dcid: bytes
    scid: bytes
    raw: bytes  # the whole packet
    pn_offset: int  # offset of the packet number inside raw (Initial only)


def split_datagram(data: bytes) -> list[LongPacket]:
    """Split coalesced long-header packets; stop at the first short header."""
    packets, pos = [], 0
    while pos < len(data) and data[pos] & 0x80:
        start = pos
        first = data[pos]
        version = int.from_bytes(data[pos + 1 : pos + 5], "big")
        pos += 5
        dlen = data[pos]
        dcid = data[pos + 1 : pos + 1 + dlen]
        pos += 1 + dlen
        slen = data[pos]
        scid = data[pos + 1 : pos + 1 + slen]
        pos += 1 + slen
        ptype = (first & 0x30) >> 4
        if ptype == 3:  # Retry runs to the end of the datagram
            packets.append(LongPacket(3, version, dcid, scid, data[start:], 0))
            break
        if ptype == 0:
            tlen, pos = read_varint(data, pos)
            pos += tlen
        length, pos = read_varint(data, pos)
        pn_offset = pos - start
        end = pos + length
        packets.append(LongPacket(ptype, version, dcid, scid, data[start:end], pn_offset))
        pos = end
    return packets


def decrypt_initial(pkt: LongPacket, keys: Keys) -> bytes:
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
    return AESGCM(keys.key).decrypt(nonce, bytes(raw[pkt.pn_offset + pn_len :]), header)


def crypto_frames(payload: bytes) -> tuple[list[tuple[int, bytes]], int | None]:
    """Return the CRYPTO frames and, if present, the CONNECTION_CLOSE error code."""
    frames, pos = [], 0
    while pos < len(payload):
        ftype = payload[pos]
        pos += 1
        if ftype in (0x00, 0x01):  # PADDING, PING
            continue
        if ftype in (0x02, 0x03):  # ACK
            _, pos = read_varint(payload, pos)
            _, pos = read_varint(payload, pos)
            count, pos = read_varint(payload, pos)
            _, pos = read_varint(payload, pos)
            for _ in range(2 * count):
                _, pos = read_varint(payload, pos)
            if ftype == 0x03:
                for _ in range(3):
                    _, pos = read_varint(payload, pos)
        elif ftype == 0x06:  # CRYPTO
            offset, pos = read_varint(payload, pos)
            length, pos = read_varint(payload, pos)
            frames.append((offset, payload[pos : pos + length]))
            pos += length
        elif ftype == 0x1C:  # CONNECTION_CLOSE
            code, pos = read_varint(payload, pos)
            return frames, code
        else:
            raise ValueError(f"unexpected frame 0x{ftype:02x} in Initial")
    return frames, None


# --- TLS parsing ------------------------------------------------------------

def parse_extensions(buf: bytes) -> dict[int, bytes]:
    exts, pos = {}, 0
    while pos + 4 <= len(buf):
        etype = int.from_bytes(buf[pos : pos + 2], "big")
        elen = int.from_bytes(buf[pos + 2 : pos + 4], "big")
        exts[etype] = buf[pos + 4 : pos + 4 + elen]
        pos += 4 + elen
    return exts


def u16_list(buf: bytes) -> list[int]:
    n = int.from_bytes(buf[:2], "big")
    return [int.from_bytes(buf[2 + i : 4 + i], "big") for i in range(0, n, 2)]


def parse_client_hello(body: bytes) -> dict:
    pos = 2 + 32
    pos += 1 + body[pos]
    pos += 2 + int.from_bytes(body[pos : pos + 2], "big")
    pos += 1 + body[pos]
    exts = parse_extensions(body[pos + 2 :])
    shares, ks = [], exts.get(0x0033, b"")
    p = 2
    while p + 4 <= len(ks):
        g = int.from_bytes(ks[p : p + 2], "big")
        n = int.from_bytes(ks[p + 2 : p + 4], "big")
        shares.append((name(GROUPS, g), n))
        p += 4 + n
    return {
        "supported_groups": [name(GROUPS, g) for g in u16_list(exts.get(0x000A, b"\x00\x00"))],
        "key_shares": shares,
        "signature_algorithms": [name(SIGALGS, s) for s in u16_list(exts.get(0x000D, b"\x00\x00"))],
        "length": len(body) + 4,
    }


def parse_server_hello(body: bytes) -> dict:
    random = body[2:34]
    pos = 34
    pos += 1 + body[pos]
    pos += 2 + 1
    exts = parse_extensions(body[pos + 2 :])
    ks = exts.get(0x0033, b"")
    group = int.from_bytes(ks[:2], "big") if len(ks) >= 2 else None
    share_len = int.from_bytes(ks[2:4], "big") if len(ks) >= 4 else 0
    return {
        "hello_retry_request": random == HRR_RANDOM,
        "selected_group": name(GROUPS, group) if group is not None else None,
        "key_share_len": share_len,
        "length": len(body) + 4,
    }


def handshake_messages(stream: bytes) -> list[tuple[int, bytes]]:
    msgs, pos = [], 0
    while pos + 4 <= len(stream):
        mtype = stream[pos]
        mlen = int.from_bytes(stream[pos + 1 : pos + 4], "big")
        if pos + 4 + mlen > len(stream):
            break
        msgs.append((mtype, stream[pos + 4 : pos + 4 + mlen]))
        pos += 4 + mlen
    return msgs


def assemble(frames: list[tuple[int, bytes]]) -> bytes:
    buf = bytearray()
    for offset, data in sorted(frames):
        if offset > len(buf):
            break  # a gap: a lost or reordered Initial we never saw
        buf[offset : offset + len(data)] = data
    return bytes(buf)


# --- trace analysis ---------------------------------------------------------

@dataclass
class Direction:
    datagrams: int = 0
    bytes: int = 0
    initial_datagrams: int = 0
    initial_bytes: int = 0
    frames: list = field(default_factory=list)
    close_code: int | None = None


def analyse(records: list[dict]) -> dict:
    stats = {"c2s": Direction(), "s2c": Direction()}
    original_dcid = None
    for rec in records:
        data = bytes.fromhex(rec["hex"])
        d = stats[rec["dir"]]
        d.datagrams += 1
        d.bytes += rec["len"]
        packets = split_datagram(data)
        if any(p.ptype == 0 for p in packets):
            d.initial_datagrams += 1
            d.initial_bytes += rec["len"]
        for pkt in packets:
            if pkt.version != QUIC_V1:
                raise ValueError(f"QUIC version 0x{pkt.version:08x} not supported")
            if pkt.ptype == 3:
                original_dcid = pkt.scid  # client re-keys Initials after Retry
                stats["c2s"].frames.clear()
                continue
            if pkt.ptype != 0:
                continue
            if rec["dir"] == "c2s" and original_dcid is None:
                original_dcid = pkt.dcid
            side = "client" if rec["dir"] == "c2s" else "server"
            payload = decrypt_initial(pkt, initial_keys(original_dcid, side))
            frames, close_code = crypto_frames(payload)
            d.frames.extend(frames)
            if close_code is not None:
                d.close_code = close_code

    result = {}
    for direction, d in stats.items():
        msgs = handshake_messages(assemble(d.frames))
        hellos = []
        for mtype, body in msgs:
            if mtype == 1:
                hellos.append({"ClientHello": parse_client_hello(body)})
            elif mtype == 2:
                hellos.append({"ServerHello": parse_server_hello(body)})
        result[direction] = {
            "datagrams": d.datagrams,
            "bytes": d.bytes,
            "initial_datagrams": d.initial_datagrams,
            "initial_bytes": d.initial_bytes,
            "hellos": hellos,
            "connection_close": None if d.close_code is None else f"0x{d.close_code:x}",
        }
    return result


def self_test() -> None:
    # RFC 9001 Appendix A.1: client Initial keys for DCID 0x8394c8f03e515708.
    k = initial_keys(bytes.fromhex("8394c8f03e515708"), "client")
    assert k.key.hex() == "1f369613dd76d5467730efcbe3b1a22d", k.key.hex()
    assert k.iv.hex() == "fa044b2f42a3fd3b46fb255c", k.iv.hex()
    assert k.hp.hex() == "9f50449e04a0e810283a1e9933adedd2", k.hp.hex()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("trace", nargs="?")
    p.add_argument("--self-test", action="store_true")
    a = p.parse_args()
    self_test()
    if a.self_test:
        print("self-test ok (RFC 9001 A.1 keys)")
        return 0
    with open(a.trace, encoding="utf-8") as f:
        records = [json.loads(line) for line in f if line.strip()]
    print(json.dumps(analyse(records), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
