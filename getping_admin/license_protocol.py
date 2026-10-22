"""Contrato GetPing v2. Idêntico no emissor e no cliente; sem estado operacional."""

import base64
import json
from datetime import datetime, timezone
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

DOMAIN = b"GetPing/license/v2\x00"
NEGATIVE_STATUSES = frozenset(
    {"suspensa", "cancelada", "expirada", "invalida", "aguardando_vinculo", "instancia_invalida"}
)


def canonical(data):
    return json.dumps(
        data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0)


def parse_utc(value):
    if not isinstance(value, str):
        raise ValueError("Data UTC ausente.")
    value = datetime.fromisoformat(value)
    if value.tzinfo is None:
        raise ValueError("Data sem fuso horário.")
    return value.astimezone(timezone.utc)


def origin(value, allow_http=False):
    if not isinstance(value, str) or any(c.isspace() or ord(c) < 32 for c in value):
        raise ValueError("Origem de licenças inválida.")
    parsed = urlsplit(value)
    if (
        parsed.scheme not in (("https", "http") if allow_http else ("https",))
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
    ):
        raise ValueError("Configure uma origem HTTPS sem caminho, credenciais ou parâmetros.")
    port = parsed.port
    host = parsed.hostname.lower()
    host = f"[{host}]" if ":" in host else host
    if port is not None and port != (443 if parsed.scheme == "https" else 80):
        host += f":{port}"
    return f"{parsed.scheme}://{host}"


def load_private(pem):
    key = serialization.load_pem_private_key(pem, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("A chave privada deve ser Ed25519.")
    return key


def load_public(pem):
    key = serialization.load_pem_public_key(pem)
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("A chave pública deve ser Ed25519.")
    return key


def sign_document(data, key):
    document = {name: value for name, value in data.items() if name != "assinatura"}
    document["protocolo"] = 2
    document["assinatura"] = base64.b64encode(key.sign(DOMAIN + canonical(document))).decode(
        "ascii"
    )
    return document


def verify_document(document, key):
    if (
        not isinstance(document, dict)
        or type(document.get("protocolo")) is not int
        or document["protocolo"] != 2
    ):
        raise ValueError("Protocolo de licença inválido.")
    unsigned = {k: v for k, v in document.items() if k != "assinatura"}
    key.verify(
        base64.b64decode(document["assinatura"], validate=True), DOMAIN + canonical(unsigned)
    )
    return document
