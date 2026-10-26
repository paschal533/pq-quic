"""aioquic as a libp2p QUIC peer, for key-exchange interop runs.

Builds a libp2p TLS certificate (libp2p TLS spec: ECDSA P-256 cert key, plus the
libp2p Public Key Extension carrying an Ed25519 identity key and its signature
over "libp2p-tls-handshake:" || SPKI). It does NOT verify the remote's libp2p
extension: the point is the TLS key exchange, which the trace decoder reads.

  listen --port P            print the peer ID, accept one handshake, then exit
  dial --port P              complete one handshake with whatever listens on P
"""

import argparse
import asyncio
import datetime
import os
import ssl
import sys
import tempfile

from aioquic.asyncio import connect, serve
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import HandshakeCompleted
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519
from cryptography.x509.oid import ObjectIdentifier

LIBP2P_EXT_OID = ObjectIdentifier("1.3.6.1.4.1.53594.1.1")
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def der_len(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    body = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(body)]) + body


def der_octets(b: bytes) -> bytes:
    return b"\x04" + der_len(len(b)) + b


def b58encode(b: bytes) -> str:
    n = int.from_bytes(b, "big")
    out = ""
    while n:
        n, r = divmod(n, 58)
        out = B58[r] + out
    return "1" * (len(b) - len(b.lstrip(b"\x00"))) + out


def libp2p_identity() -> tuple[ed25519.Ed25519PrivateKey, bytes, str]:
    key = ed25519.Ed25519PrivateKey.generate()
    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    pb = b"\x08\x01\x12\x20" + raw  # PublicKey{Type: Ed25519, Data: raw}
    peer_id = b58encode(b"\x00" + bytes([len(pb)]) + pb)  # identity multihash
    return key, pb, peer_id


def libp2p_cert(dirpath: str) -> tuple[str, str, str]:
    identity, pub_pb, peer_id = libp2p_identity()
    cert_key = ec.generate_private_key(ec.SECP256R1())
    spki = cert_key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    sig = identity.sign(b"libp2p-tls-handshake:" + spki)
    body = der_octets(pub_pb) + der_octets(sig)
    ext_value = b"\x30" + der_len(len(body)) + body
    now = datetime.datetime.now(datetime.timezone.utc)
    name = x509.Name([])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name)
        .public_key(cert_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(hours=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.UnrecognizedExtension(LIBP2P_EXT_OID, ext_value), critical=False)
        .sign(cert_key, hashes.SHA256())
    )
    cert_path = os.path.join(dirpath, "cert.pem")
    key_path = os.path.join(dirpath, "key.pem")
    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    with open(key_path, "wb") as f:
        f.write(cert_key.private_bytes(serialization.Encoding.PEM,
                                       serialization.PrivateFormat.PKCS8,
                                       serialization.NoEncryption()))
    return cert_path, key_path, peer_id


def config(is_client: bool, cert: str, key: str, groups: str | None) -> QuicConfiguration:
    cfg = QuicConfiguration(is_client=is_client, alpn_protocols=["libp2p"],
                            verify_mode=ssl.CERT_NONE)
    cfg.load_cert_chain(cert, key)
    if groups is not None:
        cfg.ssl_groups = groups  # PR #634 option; ignored by released aioquic
    return cfg


async def listen(port: int, seconds: float, groups: str | None) -> None:
    done = asyncio.Event()
    with tempfile.TemporaryDirectory() as tmp:
        cert, key, peer_id = libp2p_cert(tmp)
        from aioquic.asyncio.protocol import QuicConnectionProtocol

        class Proto(QuicConnectionProtocol):
            def quic_event_received(self, event):
                if isinstance(event, HandshakeCompleted):
                    print("handshake ok", flush=True)
                    done.set()

        server = await serve("127.0.0.1", port, configuration=config(False, cert, key, groups),
                             create_protocol=Proto)
        print(f"peer {peer_id}", flush=True)
        try:
            await asyncio.wait_for(done.wait(), seconds)
            await asyncio.sleep(0.5)
        except asyncio.TimeoutError:
            print("no handshake", flush=True)
        server.close()


async def dial(port: int, groups: str | None) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cert, key, _ = libp2p_cert(tmp)
        async with connect("127.0.0.1", port, configuration=config(True, cert, key, groups),
                           wait_connected=True):
            print("handshake ok", flush=True)
            await asyncio.sleep(0.5)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("mode", choices=["listen", "dial"])
    p.add_argument("--port", type=int, required=True)
    p.add_argument("--seconds", type=float, default=15.0)
    p.add_argument("--groups", default=None, help="PR #634 ssl_groups, e.g. X25519MLKEM768:X25519")
    a = p.parse_args()
    if a.mode == "listen":
        asyncio.run(listen(a.port, a.seconds, a.groups))
    else:
        asyncio.run(asyncio.wait_for(dial(a.port, a.groups), 10))
    return 0


if __name__ == "__main__":
    sys.exit(main())
