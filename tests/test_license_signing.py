"""Emissão, geração de chaves e configuração de produção sem serviços externos."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from getping_admin import create_app
from getping_admin.database.db import get_db
from getping_admin.license_keys import generate
from getping_admin.license_protocol import load_private, load_public, verify_document
from tests.support import IsolatedDatabaseTestCase


class SigningTests(IsolatedDatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.key = Ed25519PrivateKey.generate()
        self.app.extensions["license_signer"] = self.key
        self.app.config.update(
            PUBLIC_BASE_URL="https://central.example.test", REQUIRE_FINGERPRINT=True
        )
        with get_db() as conn:
            cid = conn.execute(
                "INSERT INTO clientes(nome_empresa,responsavel_nome,criado_em) VALUES ('Fixture','Fixture','2026-01-01')"
            ).lastrowid
            self.lid = conn.execute(
                "INSERT INTO licencas(cliente_id,chave_licenca,data_emissao,data_expiracao) VALUES (?,'FIXTURE','2026-01-01 00:00:00','2099-01-01 00:00:00')",
                (cid,),
            ).lastrowid
            conn.execute(
                "INSERT INTO license_bindings VALUES (?,NULL,NULL,datetime('now'))", (self.lid,)
            )

    def request(self, **overrides):
        return self.client.post(
            "/api/v1/licenca/validar",
            json=dict(
                chave_licenca="FIXTURE",
                fingerprint="NODE",
                protocolo=2,
                nonce="a" * 64,
                **overrides,
            ),
        )

    def test_positive_and_negative_documents_are_bound_to_request(self):
        response = self.request()
        self.assertEqual(response.status_code, 403)
        data = verify_document(response.json, self.key.public_key())
        self.assertEqual(data["status"], "aguardando_vinculo")
        with get_db() as conn:
            conn.execute("UPDATE license_bindings SET fingerprint='NODE'")
        response = self.request()
        data = verify_document(response.json, self.key.public_key())
        self.assertTrue(data["valido"])
        self.assertEqual(data["nonce"], "a" * 64)
        self.assertEqual(data["fingerprint"], "NODE")
        self.assertEqual(data["emissor"], "https://central.example.test")
        altered = dict(data, limite_hosts=999)
        with self.assertRaises(InvalidSignature):
            verify_document(altered, self.key.public_key())

    def test_unknown_key_is_signed_negative(self):
        response = self.client.post(
            "/api/v1/licenca/validar",
            json={
                "chave_licenca": "UNKNOWN",
                "fingerprint": "NODE",
                "protocolo": 2,
                "nonce": "b" * 64,
            },
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            verify_document(response.json, self.key.public_key())["status"], "invalida"
        )

    def test_bad_nonce_and_protocol_are_rejected(self):
        for fields in ({"protocolo": True}, {"protocolo": 3}, {"nonce": ""}, {"nonce": "Z" * 64}):
            payload = dict(chave_licenca="FIXTURE", fingerprint="NODE", protocolo=2, nonce="a" * 64)
            payload.update(fields)
            self.assertEqual(
                self.client.post("/api/v1/licenca/validar", json=payload).status_code, 400
            )


class KeyProvisionTests(unittest.TestCase):
    def test_key_generation_permissions_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            private = root / "private.pem"
            public = root / "public.pem"
            generate(private, public)
            self.assertEqual(private.stat().st_mode & 0o777, 0o600)
            before = private.read_bytes()
            self.assertEqual(
                load_private(before).public_key().public_bytes_raw(),
                load_public(public.read_bytes()).public_bytes_raw(),
            )
            with self.assertRaises(FileExistsError):
                generate(private, public)
            self.assertEqual(private.read_bytes(), before)
            with self.assertRaises(FileExistsError):
                generate(root / "other-private.pem", public)
            self.assertFalse((root / "other-private.pem").exists())

    def test_production_cannot_disable_transport_or_signing(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            root = Path(directory)
            private = root / "private.pem"
            generate(private, root / "public.pem")
            base = dict(
                SECRET_KEY="0123456789abcdef" * 4,
                PUBLIC_BASE_URL="https://central.example.test",
                LICENSE_SIGNING_KEY_FILE=str(private),
            )
            create_app(base)
            for overrides in (
                {"REQUIRE_HTTPS": False},
                {"REQUIRE_FINGERPRINT": False},
                {"LICENSE_SIGNING_KEY_FILE": ""},
                {"SESSION_COOKIE_SECURE": False},
            ):
                with self.subTest(overrides=overrides), self.assertRaises(RuntimeError):
                    create_app(dict(base, **overrides))
            private.chmod(0o644)
            with self.assertRaisesRegex(RuntimeError, "0600"):
                create_app(base)
