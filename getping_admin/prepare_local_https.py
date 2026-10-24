"""Prepara HTTPS local e perfil público; não altera serviços, banco ou chaves de assinatura."""

import argparse
import ipaddress
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from getping_admin.client_profile import export_profile
from getping_admin.license_protocol import origin


def prepare(destination, url, signing_key):
    url = origin(url)
    parsed = urlsplit(url)
    if parsed.port not in (None, 443):
        raise ValueError("A preparação local publica na porta HTTPS 443.")
    host = parsed.hostname
    try:
        san = x509.IPAddress(ipaddress.ip_address(host))
    except ValueError:
        # Evita caracteres de configuração Nginx em nomes fornecidos.
        import re

        if not re.fullmatch(r"[A-Za-z0-9.-]+", host):
            raise ValueError("Nome DNS inválido.") from None
        san = x509.DNSName(host)
    # Validar a chave existente antes de gerar quaisquer arquivos.
    from getping_admin.license_protocol import load_private

    load_private(Path(signing_key).read_bytes())
    destination = Path(destination)
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    now = datetime.now(timezone.utc)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "GetPing Admin Local CA")])
    server_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host)])
    ca = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            True,
        )
        .sign(ca_key, hashes.SHA256())
    )
    server = (
        x509.CertificateBuilder()
        .subject_name(server_name)
        .issuer_name(ca_name)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), True)
        .add_extension(x509.SubjectAlternativeName([san]), False)
        .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), False)
        .sign(ca_key, hashes.SHA256())
    )
    for name, key in [("ca-private.pem", ca_key), ("server.key", server_key)]:
        fd = os.open(destination / name, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(
                key.private_bytes(
                    serialization.Encoding.PEM,
                    serialization.PrivateFormat.PKCS8,
                    serialization.NoEncryption(),
                )
            )
    (destination / "ca.crt").write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    (destination / "server.crt").write_bytes(server.public_bytes(serialization.Encoding.PEM))
    nginx_host = f"[{host}]" if ":" in host else host
    (destination / "getping-admin.conf").write_text(
        f"""server {{
    listen 443 ssl;
    server_name {nginx_host};
    ssl_certificate /etc/getping-admin/tls/server.crt;
    ssl_certificate_key /etc/getping-admin/tls/server.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    client_max_body_size 32k;
    location / {{
        proxy_pass http://127.0.0.1:5001;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}
}}
""",
        encoding="utf-8",
    )
    (destination / "central.env.fragment").write_text(
        f"GETPING_PUBLIC_BASE_URL={url}\nGETPING_REQUIRE_HTTPS=1\nGETPING_PROXY_HOPS=1\nGETPING_REQUIRE_FINGERPRINT=1\n",
        encoding="utf-8",
    )
    export_profile(destination / "client-profile", url, signing_key, destination / "ca.crt")
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--signing-key", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    prepare(args.output, args.url, args.signing_key)
    print("Preparação criada sem alterar serviços/banco. Preserve CA e chaves TLS.")
    print(
        "Distribua SOMENTE a subpasta client-profile. Consulte docs/INSTALACAO_SIMPLES_CLIENTES.md."
    )


if __name__ == "__main__":
    main()
