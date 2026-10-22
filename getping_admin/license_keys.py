"""Geração explícita de chaves de emissão; não depende da factory nem do banco."""

import argparse
import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def generate(private_path, public_path):
    if private_path.resolve() == public_path.resolve():
        raise ValueError("Os destinos devem ser diferentes.")
    key = Ed25519PrivateKey.generate()
    private = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    public = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    created = []
    try:
        for path, value, mode in ((private_path, private, 0o600), (public_path, public, 0o644)):
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, mode)
            created.append(path)
            with os.fdopen(fd, "wb") as stream:
                stream.write(value)
                stream.flush()
                os.fsync(stream.fileno())
    except Exception:
        for path in created:
            path.unlink(missing_ok=True)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private", type=Path, required=True)
    parser.add_argument("--public", type=Path, required=True)
    args = parser.parse_args()
    generate(args.private, args.public)
    print("Par Ed25519 criado sem sobrescrever arquivos. Distribua somente a chave pública.")


if __name__ == "__main__":
    main()
