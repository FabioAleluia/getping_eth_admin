"""Exporta somente dados públicos para gerar instaladores GetPing já configurados."""

import argparse
import json
import os
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import serialization

from getping_admin.license_protocol import load_private, origin


def export_profile(destination, url, signing_key, ca_cert=None):
    url = origin(url)
    key = load_private(Path(signing_key).read_bytes())
    ca = None
    if ca_cert:
        ca = Path(ca_cert).read_bytes()
        if b"PRIVATE KEY" in ca:
            raise ValueError("Forneça somente o certificado público da CA.")
        certificates = x509.load_pem_x509_certificates(ca)
        if not certificates or not all(
            c.extensions.get_extension_for_class(x509.BasicConstraints).value.ca
            for c in certificates
        ):
            raise ValueError("O arquivo deve conter certificados de CA.")
        ca = b"".join(c.public_bytes(serialization.Encoding.PEM) for c in certificates)
    destination = Path(destination)
    destination.mkdir(mode=0o755, parents=True, exist_ok=False)
    (destination / "license-public.pem").write_bytes(
        key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )
    manifest = {"schema": 1, "url": url}
    if ca:
        (destination / "license-ca.crt").write_bytes(ca)
        manifest["ca"] = "license-ca.crt"
    (destination / "central.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url",
        default=os.getenv("GETPING_PUBLIC_BASE_URL"),
        required=not bool(os.getenv("GETPING_PUBLIC_BASE_URL")),
    )
    parser.add_argument(
        "--signing-key",
        type=Path,
        default=os.getenv("GETPING_LICENSE_SIGNING_KEY_FILE"),
        required=not bool(os.getenv("GETPING_LICENSE_SIGNING_KEY_FILE")),
    )
    parser.add_argument("--ca-cert", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    export_profile(args.output, args.url, args.signing_key, args.ca_cert)
    print(f"Perfil público exportado: {args.output}. Nenhuma chave privada foi copiada.")


if __name__ == "__main__":
    main()
