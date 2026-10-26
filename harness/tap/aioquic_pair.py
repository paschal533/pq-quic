"""Control run: aioquic client -> tap -> aioquic server, one handshake.

aioquic (as of 1.2/1.7) has no ML-KEM group, so the decoder should report X25519.
"""

import argparse
import asyncio
import datetime
import os
import sys
import tempfile

from aioquic.asyncio import connect, serve
from aioquic.quic.configuration import QuicConfiguration
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID


def self_signed(dirpath: str) -> tuple[str, str]:
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject).issuer_name(subject)
        .public_key(key.public_key()).serial_number(1)
        .not_valid_before(now).not_valid_after(now + datetime.timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    cert_path = os.path.join(dirpath, "cert.pem")
    key_path = os.path.join(dirpath, "key.pem")
    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    with open(key_path, "wb") as f:
        f.write(key.private_bytes(serialization.Encoding.PEM,
                                  serialization.PrivateFormat.PKCS8,
                                  serialization.NoEncryption()))
    return cert_path, key_path


async def run(server_port: int, dial_port: int) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cert, key = self_signed(tmp)
        scfg = QuicConfiguration(is_client=False, alpn_protocols=["libp2p"])
        scfg.load_cert_chain(cert, key)
        server = await serve("127.0.0.1", server_port, configuration=scfg)
        ccfg = QuicConfiguration(is_client=True, alpn_protocols=["libp2p"], verify_mode=0)
        async with connect("127.0.0.1", dial_port, configuration=ccfg) as client:
            await client.ping()
            print("handshake ok", flush=True)
        server.close()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--server-port", type=int, required=True)
    p.add_argument("--dial-port", type=int, required=True)
    a = p.parse_args()
    asyncio.run(run(a.server_port, a.dial_port))
    return 0


if __name__ == "__main__":
    sys.exit(main())
