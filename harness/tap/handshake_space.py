"""Decrypt QUIC Handshake-space packets from a quic_tap trace with a TLS key log,
and time when each client finished its handshake.

Needs SSLKEYLOGFILE output from the peers (go-pair and rust-pair both honour it).
Per client: the ClientHello random (from the client's Initial) picks the key-log
entry, the ServerHello cipher suite picks the AEAD and hash, and the client's
Handshake CRYPTO stream gives the end of its Finished message.

Output, one JSON line per client:
  finished_ms   first client datagram (as seen by the tap, before any drop) that
                carries the last byte of the client's Finished: the client's TLS
                handshake is complete when it sends this.
  server_flight_ms  first server datagram carrying the last byte of the server's Finished.
  *_delivered_ms    the same, counting only datagrams the tap delivered (not dropped).

  python handshake_space.py trace.jsonl trace.keys
"""

import json
import sys
from dataclasses import dataclass

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM, ChaCha20Poly1305
from cryptography.hazmat.primitives.hmac import HMAC

from decode_initial import (assemble, crypto_frames, decrypt_initial, handshake_messages,
                            initial_keys, split_datagram)

HS_FINISHED = 20
INITIAL, HANDSHAKE = 0, 2


@dataclass(frozen=True)
class Suite:
    hash: type
    key_len: int
    aead: type
    hp: str  # "aes" or "chacha"


SUITES = {
    0x1301: Suite(hashes.SHA256, 16, AESGCM, "aes"),
    0x1302: Suite(hashes.SHA384, 32, AESGCM, "aes"),
    0x1303: Suite(hashes.SHA256, 32, ChaCha20Poly1305, "chacha"),
}


def expand_label(secret: bytes, label: str, length: int, hash_cls: type) -> bytes:
    full = b"tls13 " + label.encode()
    info = length.to_bytes(2, "big") + bytes([len(full)]) + full + b"\x00"
    out, block, i = b"", b"", 1
    while len(out) < length:
        h = HMAC(secret, hash_cls())
        h.update(block + info + bytes([i]))
        block = h.finalize()
        out += block
        i += 1
    return out[:length]


@dataclass(frozen=True)
class HsKeys:
    suite: Suite
    key: bytes
    iv: bytes
    hp: bytes


def hs_keys(secret: bytes, suite: Suite) -> HsKeys:
    return HsKeys(suite,
                  expand_label(secret, "quic key", suite.key_len, suite.hash),
                  expand_label(secret, "quic iv", 12, suite.hash),
                  expand_label(secret, "quic hp", suite.key_len, suite.hash))


def hp_mask(k: HsKeys, sample: bytes) -> bytes:
    if k.suite.hp == "aes":
        enc = Cipher(algorithms.AES(k.hp), modes.ECB()).encryptor()
        return enc.update(sample) + enc.finalize()
    # RFC 9001 5.4.4: counter = sample[0:4] (little endian), nonce = sample[4:16];
    # cryptography's ChaCha20 takes exactly that 16-byte layout.
    enc = Cipher(algorithms.ChaCha20(k.hp, sample), mode=None).encryptor()
    return enc.update(b"\x00" * 5)


def decrypt_long(raw_packet: bytes, pn_offset: int, k: HsKeys) -> bytes:
    raw = bytearray(raw_packet)
    mask = hp_mask(k, bytes(raw[pn_offset + 4 : pn_offset + 20]))
    raw[0] ^= mask[0] & 0x0F
    pn_len = (raw[0] & 0x03) + 1
    pn = 0
    for i in range(pn_len):
        raw[pn_offset + i] ^= mask[1 + i]
        pn = (pn << 8) | raw[pn_offset + i]
    # Handshake packet numbers stay small, so the truncated number is the full one.
    nonce = bytes(a ^ b for a, b in zip(k.iv, pn.to_bytes(12, "big")))
    header = bytes(raw[: pn_offset + pn_len])
    return k.suite.aead(k.key).decrypt(nonce, bytes(raw[pn_offset + pn_len :]), header)


def load_keylog(path: str) -> dict[str, dict[str, bytes]]:
    keys: dict[str, dict[str, bytes]] = {}
    for line in open(path, encoding="utf-8"):
        parts = line.split()
        if len(parts) == 3:
            keys.setdefault(parts[1].lower(), {})[parts[0]] = bytes.fromhex(parts[2])
    return keys


def stream_end_of(msgs_stream: bytes, mtype: int) -> int | None:
    """Stream offset just past the first message of type mtype, if complete."""
    pos = 0
    for t, body in handshake_messages(msgs_stream):
        pos += 4 + len(body)
        if t == mtype:
            return pos
    return None


def first_covering(frames: list[tuple[float, int, bytes]], offset: int) -> float | None:
    """Earliest time at which a CRYPTO frame carried byte `offset`."""
    times = [t for t, off, data in frames if off <= offset < off + len(data)]
    return min(times) if times else None


def client_timing(recs: list[dict], keylog: dict[str, dict[str, bytes]]) -> dict:
    c2s_init = [r for r in recs if r["dir"] == "c2s"]
    if not c2s_init:
        return {"error": "no client datagrams"}
    t0 = c2s_init[0]["t"]
    odcid = next((p.dcid for r in c2s_init for p in split_datagram(bytes.fromhex(r["hex"])) if p.ptype == INITIAL), None)
    if odcid is None:
        return {"error": "no client Initial"}
    ikeys = {"c2s": initial_keys(odcid, "client"), "s2c": initial_keys(odcid, "server")}
    init_frames = {"c2s": [], "s2c": []}
    hs_packets = {"c2s": [], "s2c": []}  # (t, raw, pn_offset, dropped)
    for r in recs:
        for p in split_datagram(bytes.fromhex(r["hex"])):
            if p.ptype == INITIAL:
                try:
                    init_frames[r["dir"]].extend(crypto_frames(decrypt_initial(p, ikeys[r["dir"]]))[0])
                except Exception:
                    pass  # e.g. a later Initial under different keys; not needed
            elif p.ptype == HANDSHAKE:
                hs_packets[r["dir"]].append((r["t"], p.raw, p.pn_offset, bool(r.get("dropped"))))
    ch = dict(handshake_messages(assemble(init_frames["c2s"]))).get(1)
    sh = dict(handshake_messages(assemble(init_frames["s2c"]))).get(2)
    if ch is None or sh is None:
        return {"error": "no ClientHello/ServerHello"}
    entry = keylog.get(ch[2:34].hex())
    pos = 34 + 1 + sh[34]
    suite = SUITES.get(int.from_bytes(sh[pos : pos + 2], "big"))
    if entry is None or suite is None:
        return {"error": "no key-log entry" if entry is None else "unknown suite"}
    out = {}
    for d, label, field in (("c2s", "CLIENT_HANDSHAKE_TRAFFIC_SECRET", "finished_ms"),
                            ("s2c", "SERVER_HANDSHAKE_TRAFFIC_SECRET", "server_flight_ms")):
        k = hs_keys(entry[label], suite)
        frames, delivered = [], []
        for t, raw, pn_off, dropped in hs_packets[d]:
            try:
                got = [(t, off, data) for off, data in crypto_frames(decrypt_long(raw, pn_off, k))[0]]
            except Exception:
                continue
            frames.extend(got)
            if not dropped:
                delivered.extend(got)
        end = stream_end_of(assemble([(o, b) for _, o, b in frames]), HS_FINISHED)
        for name, fs in ((field, frames), (field.replace("_ms", "_delivered_ms"), delivered)):
            t = first_covering(fs, end - 1) if end else None
            out[name] = round((t - t0) * 1000, 2) if t is not None else None
    return out


def main(trace: str, keyfile: str) -> int:
    keylog = load_keylog(keyfile)
    by_client: dict[int, list[dict]] = {}
    for line in open(trace, encoding="utf-8"):
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue  # a truncated last line
        by_client.setdefault(r["client"], []).append(r)
    for c in sorted(by_client):
        print(json.dumps({"client": c, **client_timing(by_client[c], keylog)}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
